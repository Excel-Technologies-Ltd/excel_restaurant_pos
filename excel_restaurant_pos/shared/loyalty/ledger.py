"""The points ledger: immutable, lot-based, idempotent, locked.

Every credit (Earn, Bonus, a positive Adjust, a restoring Reverse) is a *lot*:
it carries `remaining_points`, an `expiry_date` and a status that moves
Pending -> Available -> Consumed / Expired / Reversed. Every debit (Redeem,
Expire, a negative Adjust, a reversing Reverse) records which lots it consumed
in its `allocations`, so a later reversal can restore exactly those lots with
their original expiry.

Rows are never edited or deleted. The only fields service code moves after
insert are a lot's `remaining_points` / `status`, a debit's
`outstanding_debt`, and allocation rows added when a debt is paid back; each
of those changes is itself evidenced by an allocation row or a new entry.

Each write carries a deterministic `idempotency_key` backed by a unique index,
so a retried hook, a replayed job or a double tap cannot post twice. Writes
that spend points first take `SELECT ... FOR UPDATE` on the account row and
re-read the balance from the ledger, so two concurrent spends serialise.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, TXN, get_programme

ALLOCATION = "ArcPOS Loyalty Allocation"

PENDING, AVAILABLE, CONSUMED, EXPIRED, REVERSED = "Pending", "Available", "Consumed", "Expired", "Reversed"
FAR_FUTURE = "9999-12-31"


class InsufficientPoints(frappe.ValidationError):
	pass


# ---------------------------------------------------------------- locking


def lock_account(account: str) -> frappe._dict:
	"""Row-lock an account for the rest of the transaction and return it."""
	rows = frappe.db.sql(
		f"""
		SELECT name, customer, programme, status, user, tier
		FROM `tab{ACCOUNT}`
		WHERE name = %s
		FOR UPDATE
		""",
		account,
		as_dict=True,
	)
	if not rows:
		frappe.throw(_("Loyalty account {0} not found.").format(account), frappe.DoesNotExistError)
	return rows[0]


def lock_row(doctype: str, name: str):
	frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE name = %s FOR UPDATE", name)


# ---------------------------------------------------------------- reads


KEY_LENGTH = 255  # ArcPOS Loyalty Transaction.idempotency_key


def norm_key(key: str) -> str:
	"""A key that fits the column. Keys carry client- or admin-chosen parts
	(event references, reward request ids), so an over-long one keeps a stable
	readable prefix -- prefix lookups still match -- and ends in a hash of the
	whole key, so two long keys never collapse into one."""
	if len(key) <= KEY_LENGTH:
		return key
	import hashlib

	return f"{key[:200]}:{hashlib.sha1(key.encode()).hexdigest()}"


def find_by_key(key: str) -> str | None:
	return frappe.db.get_value(TXN, {"idempotency_key": norm_key(key)}, "name")


def find_by_key_prefix(prefix: str, for_update: bool = False) -> list[str]:
	"""Entries whose key starts with `prefix`.

	`for_update` makes it a locking read. The database runs REPEATABLE READ, so
	a plain read after taking a lock still answers from the transaction's
	earlier snapshot and misses rows a concurrent writer just committed.
	"""
	escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	# Raw SQL: frappe.get_all has no FOR UPDATE in v14.
	return frappe.db.sql(
		f"""
		SELECT name FROM `tab{TXN}`
		WHERE idempotency_key LIKE %s
		ORDER BY creation, name
		{"FOR UPDATE" if for_update else ""}
		""",
		f"{escaped}%",
		pluck=True,
	)


def safely(title: str, fn, *args, **kwargs):
	"""Run a loyalty side effect without ever failing the order, payment or job it rides on."""
	# A unique name per call: nested calls must not replace each other's savepoint.
	savepoint = f"arcpos_loyalty_safely_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		return fn(*args, **kwargs)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(title=title, message=frappe.get_traceback())
		return None


def available_balance(account: str, for_update: bool = False) -> int:
	"""Spendable points, read from the ledger (not the cached account fields).

	`for_update` (under the account lock) reads the latest committed rows: the
	database is REPEATABLE-READ, so a plain read can return the snapshot taken
	before the lock was granted."""
	row = frappe.db.sql(
		f"""
		SELECT
			COALESCE(SUM(CASE WHEN points > 0 AND status = %s THEN remaining_points ELSE 0 END), 0)
			- COALESCE(SUM(CASE WHEN points < 0 THEN outstanding_debt ELSE 0 END), 0)
		FROM `tab{TXN}`
		WHERE account = %s
		{"LOCK IN SHARE MODE" if for_update else ""}
		""",
		(AVAILABLE, account),
	)
	return cint(row[0][0]) if row else 0


def _open_lots(account: str, for_update: bool = True) -> list[frappe._dict]:
	return frappe.db.sql(
		f"""
		SELECT name, remaining_points, expiry_date, posting_datetime
		FROM `tab{TXN}`
		WHERE account = %s AND points > 0 AND status = %s AND remaining_points > 0
		ORDER BY expiry_date IS NULL, expiry_date, posting_datetime, name
		{"FOR UPDATE" if for_update else ""}
		""",
		(account, AVAILABLE),
		as_dict=True,
	)


def plan_allocation(lots: list, points: int) -> tuple[list[dict], int]:
	"""Consume `points` from `lots` in the given (FIFO) order.

	Pure: returns the allocation rows and the shortfall that no lot covered.
	"""
	remaining = cint(points)
	allocations = []
	for lot in lots:
		if remaining <= 0:
			break
		take = min(cint(lot["remaining_points"]), remaining)
		if take <= 0:
			continue
		allocations.append(
			{
				"lot": lot["name"],
				"points": take,
				"lot_expiry_date": lot.get("expiry_date"),
				"_lot_remaining": cint(lot["remaining_points"]),
			}
		)
		remaining -= take
	return allocations, max(remaining, 0)


def plan_restore(allocations: list, already_restored: int, points: int) -> list[tuple[int, object]]:
	"""Which (points, original expiry) pieces to give back for a debit.

	Pure. Latest-expiring allocations are restored first; `already_restored`
	points are skipped from that end so successive partial restores never give
	the same allocation back twice.
	"""
	pieces = []
	skip = cint(already_restored)
	target = cint(points)
	ordered = sorted(
		allocations,
		key=lambda r: getdate(r.get("lot_expiry_date") or FAR_FUTURE),
		reverse=True,
	)
	for row in ordered:
		if target <= 0:
			break
		amount = cint(row.get("points"))
		if skip >= amount:
			skip -= amount
			continue
		amount -= skip
		skip = 0
		take = min(amount, target)
		if take > 0:
			pieces.append((take, row.get("lot_expiry_date")))
			target -= take
	return pieces


# ---------------------------------------------------------------- writes


def _account_meta(account) -> frappe._dict:
	if isinstance(account, str):
		account = frappe.db.get_value(
			ACCOUNT, account, ["name", "customer", "programme", "status", "user", "tier"], as_dict=True
		)
		if not account:
			frappe.throw(_("Loyalty account not found."), frappe.DoesNotExistError)
	return frappe._dict(account)


def _insert(values: dict, allocations: list[dict]) -> str:
	doc = frappe.get_doc({"doctype": TXN, **values})
	for row in allocations:
		doc.append("allocations", {k: v for k, v in row.items() if not k.startswith("_")})
	doc.flags.ledger_write = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _post(values: dict, allocations: list[dict] | None = None, before_insert=None) -> tuple[str, bool]:
	"""Insert one ledger row under its idempotency key.

	Returns (name, created). A duplicate key -- a retry, or a concurrent writer
	that won the race -- returns the existing row and changes nothing: the
	savepoint also rolls back the lot updates made by `before_insert`.
	"""
	key = values["idempotency_key"] = norm_key(values["idempotency_key"])
	existing = find_by_key(key)
	if existing:
		return existing, False

	savepoint = "arcpos_loyalty_post"
	frappe.db.savepoint(savepoint)
	try:
		if before_insert:
			before_insert()
		return _insert(values, allocations or []), True
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		frappe.db.rollback(save_point=savepoint)
		existing = find_by_key(key)
		if existing:
			return existing, False
		raise


def _base_values(account, transaction_type, points, key, fields) -> dict:
	programme = get_programme(account.programme)
	values = {
		"account": account.name,
		"customer": account.customer,
		"programme": account.programme,
		"posting_datetime": fields.pop("posting_datetime", None) or now_datetime(),
		"transaction_type": transaction_type,
		"points": cint(points),
		"currency_value": flt(points) * flt(programme.point_value if programme else 0),
		"idempotency_key": key,
	}
	for fieldname in (
		"source_doctype",
		"source_name",
		"campaign",
		"rule_id",
		"reward",
		"event_type",
		"reverses",
		"remarks",
		"basis_amount",
		"basis_qty",
		"basis_items",
	):
		if fields.get(fieldname) not in (None, ""):
			values[fieldname] = fields[fieldname]
	return values


def post_credit(
	account,
	transaction_type: str,
	points: int,
	key: str,
	*,
	pending_until=None,
	expiry_date=None,
	**fields,
) -> tuple[str | None, bool]:
	"""Post a credit lot. It stays Pending until `pending_until` when that is in the future."""
	points = cint(points)
	if points <= 0:
		return None, False

	account = _account_meta(account)
	values = _base_values(account, transaction_type, points, key, fields)
	today = getdate(nowdate())
	available_on = getdate(pending_until) if pending_until else today
	values.update(
		{
			"status": PENDING if available_on > today else AVAILABLE,
			"available_on": available_on,
			"expiry_date": expiry_date,
			"remaining_points": points,
		}
	)
	name, created = _post(values)
	if created and values["status"] == AVAILABLE:
		settle_debt(account.name)
	return name, created


def post_debit(
	account,
	transaction_type: str,
	points: int,
	key: str,
	*,
	allow_negative: bool = False,
	**fields,
) -> tuple[str | None, bool]:
	"""Post a debit, consuming Available lots FIFO by earliest expiry.

	The caller must already hold the account lock (lock_account), so the
	balance read here cannot change underneath it. A shortfall raises
	InsufficientPoints, or becomes a negative balance when `allow_negative`.
	"""
	points = cint(points)
	if points <= 0:
		return None, False

	existing = find_by_key(key)
	if existing:
		return existing, False

	account = _account_meta(account)
	allocations, shortfall = plan_allocation(_open_lots(account.name), points)
	if shortfall and not allow_negative:
		available = available_balance(account.name)
		raise InsufficientPoints(
			_("Not enough loyalty points: {0} requested, {1} available.").format(points, max(available, 0))
		)

	values = _base_values(account, transaction_type, -points, key, fields)
	values.update({"status": CONSUMED, "outstanding_debt": shortfall})

	def consume():
		for row in allocations:
			left = row["_lot_remaining"] - row["points"]
			frappe.db.set_value(
				TXN,
				row["lot"],
				{"remaining_points": left, "status": CONSUMED if left <= 0 else AVAILABLE},
				update_modified=False,
			)

	return _post(values, allocations, before_insert=consume)


def settle_debt(account: str):
	"""Pay a negative balance back from Available lots, oldest debt first."""
	debts = frappe.db.sql(
		f"""
		SELECT name, outstanding_debt
		FROM `tab{TXN}`
		WHERE account = %s AND points < 0 AND outstanding_debt > 0
		ORDER BY posting_datetime, name
		FOR UPDATE
		""",
		account,
		as_dict=True,
	)

	for debt in debts:
		lots = _open_lots(account)
		if not lots:
			return
		allocations, shortfall = plan_allocation(lots, debt.outstanding_debt)
		next_idx = cint(
			frappe.db.sql(f"SELECT COALESCE(MAX(idx), 0) FROM `tab{ALLOCATION}` WHERE parent = %s", debt.name)[0][0]
		)
		for row in allocations:
			next_idx += 1
			left = row["_lot_remaining"] - row["points"]
			frappe.db.set_value(
				TXN, row["lot"], {"remaining_points": left, "status": CONSUMED if left <= 0 else AVAILABLE}, update_modified=False
			)
			frappe.get_doc(
				{
					"doctype": ALLOCATION,
					"parent": debt.name,
					"parenttype": TXN,
					"parentfield": "allocations",
					"idx": next_idx,
					"lot": row["lot"],
					"points": row["points"],
					"lot_expiry_date": row["lot_expiry_date"],
				}
			).db_insert()
		frappe.db.set_value(TXN, debt.name, "outstanding_debt", shortfall, update_modified=False)
		if shortfall:
			return


def reverse_credit(
	account,
	lot_name: str,
	key: str,
	*,
	points: int | None = None,
	allow_negative: bool = False,
	**fields,
) -> tuple[str | None, int]:
	"""Take back (part of) a credit lot. Returns (entry, points not recovered).

	What is still on the lot is simply removed. What the member already spent
	becomes a negative balance when `allow_negative`, otherwise it is left and
	reported as the shortfall. Points that expired are not taken twice.
	"""
	existing = find_by_key(key)
	if existing:
		return existing, 0

	account = _account_meta(account)
	rows = frappe.db.sql(
		f"""
		SELECT name, points, remaining_points, status, expiry_date
		FROM `tab{TXN}` WHERE name = %s FOR UPDATE
		""",
		lot_name,
		as_dict=True,
	)
	if not rows or cint(rows[0].points) <= 0:
		return None, 0
	lot = rows[0]

	already = -cint(
		frappe.db.sql(
			f"SELECT COALESCE(SUM(points), 0) FROM `tab{TXN}` WHERE reverses = %s AND transaction_type = 'Reverse' AND points < 0",
			lot.name,
		)[0][0]
	)
	target = min(cint(points) if points is not None else cint(lot.points), cint(lot.points) - already)
	if target <= 0:
		return None, 0

	from_lot = min(target, cint(lot.remaining_points)) if lot.status in (PENDING, AVAILABLE) else 0
	spent = cint(
		frappe.db.sql(
			f"""
			SELECT COALESCE(SUM(a.points), 0)
			FROM `tab{ALLOCATION}` a JOIN `tab{TXN}` d ON d.name = a.parent
			WHERE a.lot = %s AND d.transaction_type IN ('Redeem', 'Adjust')
			""",
			lot.name,
		)[0][0]
	)
	debt = min(target - from_lot, spent) if allow_negative else 0
	shortfall = target - from_lot - debt
	total = from_lot + debt
	if total <= 0:
		return None, shortfall

	if shortfall and not fields.get("remarks"):
		fields["remarks"] = _("{0} point(s) were already spent or expired and could not be reversed.").format(shortfall)

	values = _base_values(account, "Reverse", -total, key, {**fields, "reverses": lot.name})
	values.update({"status": CONSUMED, "outstanding_debt": debt})
	allocations = [{"lot": lot.name, "points": from_lot, "lot_expiry_date": lot.expiry_date}] if from_lot else []

	def consume():
		if from_lot:
			left = cint(lot.remaining_points) - from_lot
			frappe.db.set_value(
				TXN, lot.name, {"remaining_points": left, "status": REVERSED if left <= 0 else lot.status}, update_modified=False
			)

	name, _created = _post(values, allocations, before_insert=consume)
	return name, shortfall


def restore_debit(
	account,
	debit_name: str,
	key_prefix: str,
	*,
	points: int | None = None,
	grace_days: int = 7,
	**fields,
) -> list[str]:
	"""Give back (part of) a debit as new lots carrying the original lots' expiry.

	An expiry already past gets `grace_days` from today, so the member can still
	use the points. Idempotent per `key_prefix`.
	"""
	done = find_by_key_prefix(f"{key_prefix}:")
	if done:
		return done

	account = _account_meta(account)
	debit = frappe.get_doc(TXN, debit_name)
	if cint(debit.points) >= 0:
		return []

	restored = cint(
		frappe.db.sql(
			f"SELECT COALESCE(SUM(points), 0) FROM `tab{TXN}` WHERE reverses = %s AND points > 0",
			debit.name,
		)[0][0]
	)
	restorable = -cint(debit.points) - restored - cint(debit.outstanding_debt)
	target = min(cint(points) if points is not None else restorable, restorable)
	if points is None and cint(debit.outstanding_debt):
		# A full undo also forgives what the debit still owed (a card-paid
		# order whose points ran out before it submitted): nothing was taken.
		frappe.db.set_value(TXN, debit.name, "outstanding_debt", 0, update_modified=False)
	if target <= 0:
		return []

	pieces = plan_restore([row.as_dict() for row in debit.allocations], restored, target)

	today = getdate(nowdate())
	names = []
	for idx, (take, expiry) in enumerate(pieces):
		if expiry and getdate(expiry) < today:
			expiry = add_days(today, cint(grace_days))
		name, _created = post_credit(
			account,
			"Reverse",
			take,
			f"{key_prefix}:{idx}",
			expiry_date=expiry,
			reverses=debit.name,
			**fields,
		)
		if name:
			names.append(name)
	return names


def expire_lot(account, lot_name: str, key: str, remarks: str | None = None) -> str | None:
	"""Expire whatever is left on one lot."""
	rows = frappe.db.sql(
		f"SELECT name, remaining_points, expiry_date, status FROM `tab{TXN}` WHERE name = %s FOR UPDATE",
		lot_name,
		as_dict=True,
	)
	if not rows or rows[0].status not in (PENDING, AVAILABLE) or cint(rows[0].remaining_points) <= 0:
		return None
	lot = rows[0]
	account = _account_meta(account)

	values = _base_values(account, "Expire", -cint(lot.remaining_points), key, {"remarks": remarks, "reverses": lot.name})
	values["status"] = CONSUMED
	allocations = [{"lot": lot.name, "points": cint(lot.remaining_points), "lot_expiry_date": lot.expiry_date}]

	def consume():
		frappe.db.set_value(TXN, lot.name, {"remaining_points": 0, "status": EXPIRED}, update_modified=False)

	name, _created = _post(values, allocations, before_insert=consume)
	return name


def release_pending(account: str | None = None, on_date=None) -> list[str]:
	"""Make Pending lots whose `available_on` has come Available. Returns the accounts touched."""
	filters = {"status": PENDING, "available_on": ["<=", getdate(on_date or nowdate())], "points": [">", 0]}
	if account:
		filters["account"] = account
	lots = frappe.get_all(TXN, filters=filters, fields=["name", "account"])
	for lot in lots:
		frappe.db.set_value(TXN, lot.name, "status", AVAILABLE, update_modified=False)
	accounts = sorted({lot.account for lot in lots})
	for name in accounts:
		settle_debt(name)
	return accounts


# ---------------------------------------------------------------- cache


def compute_balances(account: str) -> dict:
	row = frappe.db.sql(
		f"""
		SELECT
			COALESCE(SUM(CASE WHEN t.transaction_type IN ('Earn', 'Bonus')
				OR (t.transaction_type = 'Adjust' AND t.points > 0) THEN t.points ELSE 0 END), 0) AS earned,
			COALESCE(SUM(CASE WHEN t.transaction_type = 'Reverse' AND t.points < 0
				AND r.transaction_type IN ('Earn', 'Bonus', 'Adjust') THEN -t.points ELSE 0 END), 0) AS earned_reversed,
			COALESCE(SUM(CASE WHEN t.transaction_type = 'Redeem' THEN -t.points ELSE 0 END), 0) AS redeemed,
			COALESCE(SUM(CASE WHEN t.transaction_type = 'Reverse' AND t.points > 0
				AND r.transaction_type = 'Redeem' THEN t.points ELSE 0 END), 0) AS redeemed_restored,
			COALESCE(SUM(CASE WHEN t.transaction_type = 'Expire' THEN -t.points ELSE 0 END), 0) AS expired,
			COALESCE(SUM(CASE WHEN t.points > 0 AND t.status = 'Available' THEN t.remaining_points ELSE 0 END), 0) AS lots,
			COALESCE(SUM(CASE WHEN t.points > 0 AND t.status = 'Pending' THEN t.remaining_points ELSE 0 END), 0) AS pending,
			COALESCE(SUM(CASE WHEN t.points < 0 THEN t.outstanding_debt ELSE 0 END), 0) AS debt
		FROM `tab{TXN}` t
		LEFT JOIN `tab{TXN}` r ON r.name = t.reverses
		WHERE t.account = %s
		""",
		account,
		as_dict=True,
	)[0]

	nxt = frappe.db.sql(
		f"""
		SELECT expiry_date, SUM(remaining_points) AS points
		FROM `tab{TXN}`
		WHERE account = %s AND points > 0 AND status = 'Available'
			AND remaining_points > 0 AND expiry_date IS NOT NULL
		GROUP BY expiry_date
		ORDER BY expiry_date
		LIMIT 1
		""",
		account,
		as_dict=True,
	)

	return {
		"available_points": cint(row.lots) - cint(row.debt),
		"pending_points": cint(row.pending),
		"lifetime_earned": cint(row.earned) - cint(row.earned_reversed),
		"lifetime_redeemed": cint(row.redeemed) - cint(row.redeemed_restored),
		"lifetime_expired": cint(row.expired),
		"next_expiry_date": nxt[0].expiry_date if nxt else None,
		"next_expiry_points": cint(nxt[0].points) if nxt else 0,
	}


def reconcile_account_cache():
	"""Weekly: recompute every account from the ledger and report any drift."""
	fields = ("available_points", "pending_points", "lifetime_earned", "lifetime_redeemed", "lifetime_expired")
	drifted = []
	for row in frappe.get_all(ACCOUNT, fields=["name", *fields]):
		values = compute_balances(row.name)
		if any(cint(row.get(f)) != cint(values[f]) for f in fields):
			drifted.append(f"{row.name}: " + ", ".join(f"{f} {row.get(f)} -> {values[f]}" for f in fields if cint(row.get(f)) != cint(values[f])))
			frappe.db.set_value(ACCOUNT, row.name, values, update_modified=False)
		frappe.db.commit()
	if drifted:
		frappe.log_error(title="Loyalty account cache drift corrected", message="\n".join(drifted[:500]))
	return len(drifted)


def recompute_cache(account: str, touch_activity: bool = False, sync_wallet: bool = True) -> dict:
	"""Rewrite the cached balance fields on the account from the ledger."""
	values = compute_balances(account)
	if touch_activity:
		values["last_activity_at"] = now_datetime()
	frappe.db.set_value(ACCOUNT, account, values, update_modified=False)
	if sync_wallet:
		from excel_restaurant_pos.shared.loyalty.wallet.sync import schedule_sync

		schedule_sync(account)
	return values
