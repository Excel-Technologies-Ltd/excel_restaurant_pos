"""Earning points on purchases: invoice context, awards, preview, hooks."""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate

from excel_restaurant_pos.shared.loyalty import campaigns, ledger, rules
from excel_restaurant_pos.shared.loyalty.accounts import account_for_customer, enrol
from excel_restaurant_pos.shared.loyalty.segments import account_segments
from excel_restaurant_pos.shared.loyalty.settings import (
	ACCOUNT,
	TXN,
	channel_allowed,
	channel_key,
	get_active_programme,
	get_settings,
	is_enabled,
	is_excluded_customer,
)
from excel_restaurant_pos.shared.loyalty.tiers import lowest_tier, multiplier_for

INVOICE = "Sales Invoice"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
PAID_TOLERANCE = 0.005


# Kept here too: callers and tests import it from earning.
safely = ledger.safely


def expiry_for(programme, available_on):
	if programme.expiry_mode == "Fixed Days per Lot" and cint(programme.expiry_days) > 0:
		return add_days(getdate(available_on), cint(programme.expiry_days))
	return None


def pending_until(programme, posting_date):
	days = cint(programme.pending_days)
	return add_days(getdate(posting_date or nowdate()), days) if days > 0 else None


# ---------------------------------------------------------------- context


def _group_ancestors(groups: set) -> dict:
	out = {}
	for group in groups:
		bounds = frappe.db.get_value("Item Group", group, ["lft", "rgt"], as_dict=True) if group else None
		if not bounds:
			out[group] = ()
			continue
		out[group] = tuple(
			frappe.get_all("Item Group", filters={"lft": ["<", bounds.lft], "rgt": [">", bounds.rgt]}, pluck="name")
		)
	return out


def _excluded(programme, line) -> bool:
	if cint(programme.exclude_gift_card_items) and cint(line.get("is_gift_card")):
		return True
	excluded = {row.item_group for row in programme.get("exclude_item_groups") or []}
	if not excluded:
		return False
	return line.get("item_group") in excluded or bool(excluded & set(line.get("item_group_ancestors") or ()))


def build_lines(raw_lines, programme, scale: float = 1.0) -> list[dict]:
	"""Eligible lines with item group ancestors attached and amounts scaled to the earn basis."""
	ancestors = _group_ancestors({line.get("item_group") for line in raw_lines})
	lines = []
	for line in raw_lines:
		line = dict(line)
		line["item_group_ancestors"] = ancestors.get(line.get("item_group"), ())
		if _excluded(programme, line):
			continue
		line["amount"] = flt(line.get("amount")) * scale
		lines.append(line)
	return lines


def invoice_raw_lines(doc) -> list[dict]:
	return [
		{
			"item_code": item.get("item_code"),
			"item_group": item.get("item_group"),
			"brand": item.get("brand"),
			"qty": flt(item.get("qty")),
			"amount": flt(item.get("base_net_amount") or item.get("net_amount") or item.get("amount")),
			"is_gift_card": cint(item.get("custom_is_gift_card_item")),
		}
		for item in doc.get("items") or []
	]


def basis_scale(programme, net_total: float, grand_total: float, loyalty_value: float) -> float:
	"""Factor from line net amounts to the amount points are earned on.

	Line net amounts already exclude tax and carry their share of any coupon
	or gift card discount. Grand Total basis scales them up by the tax; the
	part of the order paid with points is taken out unless the programme
	earns on it.
	"""
	scale = 1.0
	if programme.earn_basis == "Grand Total" and flt(net_total):
		scale = flt(grand_total) / flt(net_total)
	if flt(loyalty_value) and not cint(programme.earn_on_loyalty_paid_amount) and flt(grand_total) > 0:
		scale *= max(flt(grand_total) - flt(loyalty_value), 0) / flt(grand_total)
	return scale


def member_context(account_name: str | None, programme) -> dict:
	if not account_name:
		tier = lowest_tier(programme)
		return {
			"account": None,
			"tier": tier.tier_name if tier else None,
			"segments": [],
			"order_count": 0,
			"days_since_last_order": None,
		}

	account = frappe.db.get_value(ACCOUNT, account_name, ["name", "tier", "order_count", "last_order_at"], as_dict=True)
	days = (now_datetime() - get_datetime(account.last_order_at)).days if account.last_order_at else None
	return {
		"account": account.name,
		"tier": account.tier,
		"segments": account_segments(account.name),
		"order_count": cint(account.order_count),
		"days_since_last_order": days,
	}


def order_number(customer: str, invoice: str | None = None, created=None) -> int:
	"""This order's place among the customer's orders.

	Counted by creation, not by what happens to be submitted now: a second
	order submitted before the first one is paid must not make the first one
	its customer's order number 2.
	"""
	filters = {"customer": customer, "docstatus": 1, "is_return": 0}
	if invoice:
		filters["name"] = ["!=", invoice]
	if created:
		filters["creation"] = ["<", created]
	return frappe.db.count(INVOICE, filters) + 1


def invoice_context(doc, programme, account_name: str | None) -> dict:
	posting = get_datetime(f"{doc.posting_date} {doc.get('posting_time') or '00:00:00'}")
	scale = basis_scale(
		programme,
		doc.get("base_net_total") or doc.get("net_total"),
		doc.get("base_grand_total") or doc.get("grand_total"),
		flt(doc.get("custom_loyalty_redeem_value")),
	)
	lines = build_lines(invoice_raw_lines(doc), programme, scale)
	return {
		"kind": "purchase",
		"invoice": doc.name,
		"customer": doc.customer,
		"channel": channel_key(doc),
		"territory": doc.get("territory"),
		"posting_datetime": posting,
		"weekday": WEEKDAYS[posting.weekday()],
		"hour": posting.hour,
		"order_number": order_number(doc.customer, doc.name, doc.get("creation")),
		"lines": lines,
		"eligible_amount": sum(line["amount"] for line in lines),
		"total": flt(doc.get("grand_total")),
		**member_context(account_name, programme),
	}


def scopes_for(programme, ctx, force_campaigns=None) -> list[dict]:
	chosen = campaigns.select_for_context(programme.name, ctx)
	if force_campaigns:
		names = {c.name for c in chosen}
		chosen = campaigns.choose_stack(chosen + [c for c in force_campaigns if c.name not in names])
	return [rules.base_scope(programme), *[rules.campaign_scope(c) for c in chosen]]


def evaluate(programme, ctx, force_campaigns=None) -> list[dict]:
	return rules.evaluate(
		ctx,
		scopes_for(programme, ctx, force_campaigns),
		tier_multiplier=multiplier_for(programme, ctx.get("tier")),
		rounding=programme.points_rounding or "Floor",
		tier_name=ctx.get("tier"),
	)


# ---------------------------------------------------------------- awarding


def is_paid(invoice: str) -> bool:
	outstanding = frappe.db.get_value(INVOICE, invoice, "outstanding_amount")
	return outstanding is not None and flt(outstanding) <= PAID_TOLERANCE


def stamp_invoice(invoice: str, values: dict):
	"""Write loyalty fields on a (possibly submitted) invoice, skipping any not migrated yet."""
	meta = frappe.get_meta(INVOICE)
	values = {k: v for k, v in values.items() if meta.has_field(k)}
	if values:
		frappe.db.set_value(INVOICE, invoice, values, update_modified=False)


def _record_order(account: str, doc):
	values = {"order_count": frappe.db.count(INVOICE, {"customer": doc.customer, "docstatus": 1, "is_return": 0})}
	ordered_at = get_datetime(f"{doc.posting_date} {doc.get('posting_time') or '00:00:00'}")
	last = frappe.db.get_value(ACCOUNT, account, "last_order_at")
	# An older order awarded late (the backfill) must not move it back.
	if not last or get_datetime(last) < ordered_at:
		values["last_order_at"] = ordered_at
	frappe.db.set_value(ACCOUNT, account, values, update_modified=False)


def award_for_invoice(invoice, backfill: bool = False) -> list[str]:
	"""Award the points a paid (or submitted, per programme) invoice earns. Idempotent.

	`backfill` is the hourly backstop, which comes back to every recent order
	that earned nothing: one that earns nothing again changes nothing.
	"""
	doc = frappe.get_doc(INVOICE, invoice) if isinstance(invoice, str) else invoice
	if cint(doc.docstatus) != 1 or cint(doc.get("is_return")):
		return []

	programme = get_active_programme(doc.posting_date)
	if not programme or (programme.company and doc.company != programme.company):
		return []
	if is_excluded_customer(doc.customer):
		return []
	if not channel_allowed(programme, "earn", channel_key(doc)):
		return []
	if programme.earn_on != "Submitted" and not is_paid(doc.name):
		return []

	# Points are awarded once per invoice: a rule edited between submit and
	# payment must not top the order up with a second set of awards.
	already = ledger.find_by_key_prefix(f"earn:{doc.name}:")
	if already:
		return already

	# Always the invoice's own customer: a stamped account can be stale (copied
	# by an amendment, or left from before the customer was changed).
	account = account_for_customer(doc.customer)
	if not account and cint(get_settings().auto_enrol_on_first_order):
		account = enrol(doc.customer, source="First Order")
	if not account:
		return []

	locked = ledger.lock_account(account)
	if locked.status != "Active":
		return []
	# Again under the lock, and as a locking read: the submit hook and the
	# payment hook can award the same invoice at once, and the loser must not
	# go on to overwrite the winner's stamped total with 0.
	already = ledger.find_by_key_prefix(f"earn:{doc.name}:", for_update=True)
	if already:
		return already

	ctx = invoice_context(doc, programme, account)
	awards = evaluate(programme, ctx)
	if backfill and not awards and ctx["order_number"] != 1:
		return []

	until = pending_until(programme, doc.posting_date)
	expiry = expiry_for(programme, max(getdate(until), getdate(nowdate())) if until else nowdate())

	names, total, touched = [], 0, set()
	for award in awards:
		points = campaigns.capped_points(award.get("campaign"), account, award["points"])
		if points <= 0:
			continue
		name, created = ledger.post_credit(
			locked,
			award["transaction_type"],
			points,
			f"earn:{doc.name}:{award['scope']}:{award['rule_id']}",
			pending_until=until,
			expiry_date=expiry,
			source_doctype=INVOICE,
			source_name=doc.name,
			campaign=award.get("campaign"),
			rule_id=award.get("rule_id"),
			remarks=award.get("rule_name"),
			basis_amount=award.get("basis_amount"),
			basis_qty=award.get("basis_qty"),
			basis_items=json.dumps(award["basis_items"]) if award.get("basis_items") else None,
		)
		if name:
			names.append(name)
			total += points if created else 0
			if award.get("campaign"):
				touched.add(award["campaign"])

	_record_order(account, doc)
	ledger.recompute_cache(account, touch_activity=True)
	stamp_invoice(doc.name, {"custom_loyalty_points_earned": total, "custom_loyalty_account": account})
	for campaign in touched:
		campaigns.update_stats(campaign)

	# Each in its own savepoint: a failing event rule or tier update must not
	# roll back the points the order has already earned.
	if ctx["order_number"] == 1:
		from excel_restaurant_pos.shared.loyalty.events import emit

		safely(
			"Loyalty first-order event failed",
			emit,
			"first_order",
			doc.customer,
			reference_doctype=INVOICE,
			reference_name=doc.name,
		)

	from excel_restaurant_pos.shared.loyalty.notifications import enqueue_notification
	from excel_restaurant_pos.shared.loyalty.tiers import evaluate as evaluate_tier

	safely("Loyalty tier update failed", evaluate_tier, account, reason=f"Order {doc.name}")
	if total:
		enqueue_notification(
			account,
			"earned",
			key=f"earned:{doc.name}",
			context={"points": total, "invoice": doc.name, "pending": bool(until and getdate(until) > getdate(nowdate()))},
		)
	return names


# ---------------------------------------------------------------- preview


def _summary(awards, programme) -> dict:
	total = sum(a["points"] for a in awards)
	return {
		"points": total,
		"value": flt(total * flt(programme.point_value), 2),
		"pending_days": cint(programme.pending_days),
		"awards": [
			{k: a.get(k) for k in ("scope", "campaign", "rule_id", "rule_name", "transaction_type", "points")}
			for a in awards
		],
	}


def preview_for_invoice(doc, force_campaigns=None) -> dict:
	"""What an invoice (draft or not) earns, without writing anything."""
	programme = get_active_programme(doc.posting_date)
	if not programme or is_excluded_customer(doc.customer):
		return {"points": 0, "value": 0, "awards": [], "eligible": False}
	if not channel_allowed(programme, "earn", channel_key(doc)):
		return {"points": 0, "value": 0, "awards": [], "eligible": False, "reason": "channel"}

	account = account_for_customer(doc.customer)
	ctx = invoice_context(doc, programme, account)
	return {"eligible": True, **_summary(evaluate(programme, ctx, force_campaigns), programme)}


def preview_for_cart(customer: str | None, items: list, order_from=None, service_type=None, territory=None) -> dict:
	"""What a cart would earn: prices from the cart, tax not known yet (net basis)."""
	programme = get_active_programme()
	if not programme:
		return {"points": 0, "value": 0, "awards": [], "eligible": False}

	channel = channel_key(frappe._dict(custom_order_from=order_from, custom_service_type=service_type))
	if not channel_allowed(programme, "earn", channel):
		return {"points": 0, "value": 0, "awards": [], "eligible": False, "reason": "channel"}

	raw = []
	for item in items or []:
		code = item.get("item_code")
		if not code:
			continue
		meta = frappe.db.get_value("Item", code, ["item_group", "brand", "custom_is_gift_card_item"], as_dict=True) or {}
		qty = flt(item.get("qty")) or 1
		raw.append(
			{
				"item_code": code,
				"item_group": meta.get("item_group"),
				"brand": meta.get("brand"),
				"qty": qty,
				"amount": flt(item.get("amount")) or flt(item.get("rate")) * qty,
				"is_gift_card": cint(meta.get("custom_is_gift_card_item")),
			}
		)

	lines = build_lines(raw, programme)
	now = now_datetime()
	account = account_for_customer(customer) if customer else None
	ctx = {
		"kind": "purchase",
		"customer": customer,
		"channel": channel,
		"territory": territory,
		"posting_datetime": now,
		"weekday": WEEKDAYS[now.weekday()],
		"hour": now.hour,
		"order_number": order_number(customer) if customer else 1,
		"lines": lines,
		"eligible_amount": sum(line["amount"] for line in lines),
		"total": sum(flt(line["amount"]) for line in raw),
		**member_context(account, programme),
	}
	return {"eligible": True, **_summary(evaluate(programme, ctx), programme)}


# ---------------------------------------------------------------- hooks


def on_invoice_submit(doc, method=None):
	"""Sales Invoice on_submit: earn now when the programme earns on submit or the order is paid."""
	if cint(doc.get("is_return")) or not is_enabled():
		return
	safely("Loyalty earning on submit failed", award_for_invoice, doc.name)


def on_payment_settled(doc, method=None):
	"""Payment Entry on_submit: the invoice it pays off may have just become Paid."""
	if not is_enabled():
		return
	for ref in doc.get("references") or []:
		if ref.reference_doctype == INVOICE and ref.reference_name and is_paid(ref.reference_name):
			safely("Loyalty earning on payment failed", award_for_invoice, ref.reference_name)


def backfill_missed_awards(days: int = 30):
	"""Hourly backstop: recent paid invoices of members that have earned nothing yet.

	A month back, newest first: an order paid days later (a Journal Entry, a
	reconciliation) never passes through the Payment Entry hook. An order with
	a return is left alone: its points would be awarded in full with nothing
	left to reverse the returned part.
	"""
	if not is_enabled() or not get_active_programme():
		return
	rows = frappe.db.sql(
		f"""
		SELECT si.name
		FROM `tabSales Invoice` si
		JOIN `tab{ACCOUNT}` acc ON acc.customer = si.customer AND acc.status = 'Active'
		WHERE si.docstatus = 1 AND si.is_return = 0 AND si.outstanding_amount <= %s
			AND si.posting_date >= %s
			AND NOT EXISTS (
				SELECT 1 FROM `tab{TXN}` t
				WHERE t.source_doctype = 'Sales Invoice' AND t.source_name = si.name
					AND t.transaction_type IN ('Earn', 'Bonus')
			)
			AND NOT EXISTS (
				SELECT 1 FROM `tabSales Invoice` r WHERE r.return_against = si.name AND r.docstatus = 1
			)
		ORDER BY si.posting_date DESC, si.creation DESC
		LIMIT 500
		""",
		(PAID_TOLERANCE, add_days(nowdate(), -cint(days))),
		pluck=True,
	)
	for name in rows:
		safely("Loyalty earning backfill failed", award_for_invoice, name, backfill=True)
		frappe.db.commit()
