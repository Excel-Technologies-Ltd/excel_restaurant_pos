"""Reward catalogue: points buy a single-use voucher issued through the coupon engine."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from excel_restaurant_pos.shared.coupon.services import (
	COUPON_STATUS_ACTIVE,
	COUPON_STATUS_EXPIRED,
	PROMOTIONAL_COUPON_TYPE,
	generate_unique_coupon_code,
	get_coupon_settings,
	resolve_applied_coupon_code,
)
from excel_restaurant_pos.shared.loyalty import holds, ledger
from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, REWARD, TXN, get_settings

VOUCHER_PREFIX = "RWD######"


def _tiers(text) -> set[str]:
	return {t.strip() for t in (text or "").split(",") if t.strip()}


def _issued(reward: str, account: str | None = None, for_update: bool = False) -> int:
	"""Vouchers issued for a reward that were not refunded.

	`for_update` reads the latest committed rows (REPEATABLE READ would
	otherwise answer from the transaction's earlier snapshot).
	"""
	conditions, values = "t.reward = %s AND t.transaction_type = 'Redeem'", [reward]
	if account:
		conditions += " AND t.account = %s"
		values.append(account)
	row = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM `tab{TXN}` t
		WHERE {conditions}
			AND NOT EXISTS (SELECT 1 FROM `tab{TXN}` r WHERE r.reverses = t.name AND r.points > 0)
		{"LOCK IN SHARE MODE" if for_update else ""}
		""",
		values,
	)
	return cint(row[0][0])


def is_live(reward, on_date=None) -> bool:
	on_date = getdate(on_date or nowdate())
	if not cint(reward.enabled):
		return False
	if reward.active_from and on_date < getdate(reward.active_from):
		return False
	if reward.active_to and on_date > getdate(reward.active_to):
		return False
	return True


def refusal(reward, account, for_update: bool = False) -> str | None:
	"""Why this member cannot take this reward now, or None."""
	if not is_live(reward):
		return _("This reward is not available.")
	if reward.programme != account.programme:
		return _("This reward belongs to another programme.")
	tiers = _tiers(reward.eligible_tiers)
	if tiers and account.tier not in tiers:
		return _("This reward is for {0} members.").format(", ".join(sorted(tiers)))
	if cint(reward.stock_limit) and _issued(reward.name, for_update=for_update) >= cint(reward.stock_limit):
		return _("This reward is out of stock.")
	if cint(reward.per_customer_limit) and _issued(reward.name, account.name, for_update=for_update) >= cint(reward.per_customer_limit):
		return _("You have already redeemed this reward the maximum number of times.")
	return None


REWARD_FIELDS = [
	"name",
	"reward_name",
	"description",
	"image",
	"reward_type",
	"points_cost",
	"discount_type",
	"discount_value",
	"free_item",
	"voucher_validity_days",
	"stock_limit",
	"per_customer_limit",
	"eligible_tiers",
	"active_from",
	"active_to",
	"enabled",
	"programme",
]


def list_rewards(account_name: str) -> list[dict]:
	account = frappe.db.get_value(ACCOUNT, account_name, ["name", "programme", "tier", "available_points"], as_dict=True)
	rows = frappe.get_all(
		REWARD,
		filters={"programme": account.programme, "enabled": 1},
		fields=REWARD_FIELDS,
		order_by="points_cost asc",
	)
	out = []
	for row in rows:
		if not is_live(row):
			continue
		reason = refusal(row, account)
		out.append(
			{
				"reward": row.name,
				"reward_name": row.reward_name,
				"description": row.description,
				"image": row.image,
				"reward_type": row.reward_type,
				"points_cost": cint(row.points_cost),
				"discount_type": row.discount_type,
				"discount_value": flt(row.discount_value),
				"free_item": row.free_item,
				"voucher_validity_days": cint(row.voucher_validity_days),
				"affordable": cint(account.available_points) >= cint(row.points_cost),
				"eligible": reason is None,
				"reason": reason,
				"remaining_stock": (cint(row.stock_limit) - _issued(row.name)) if cint(row.stock_limit) else None,
			}
		)
	return out


def _free_item_value(item_code: str) -> float:
	price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
	rate = frappe.db.get_value(
		"Item Price", {"item_code": item_code, "selling": 1, "price_list": price_list}, "price_list_rate"
	)
	return flt(rate or frappe.db.get_value("Item", item_code, "standard_rate"))


def _pricing_rule() -> str:
	settings = get_settings()
	rule = (settings.voucher_pricing_rule if settings else None) or (get_coupon_settings() or frappe._dict()).get(
		"default_pricing_rule"
	)
	if not rule or not frappe.db.exists("Pricing Rule", rule):
		frappe.throw(_("Set a Reward Voucher Pricing Rule in ArcPOS Loyalty Settings."))
	return rule


def _issue_voucher(reward, account) -> frappe._dict:
	valid_from = getdate(nowdate())
	valid_upto = add_days(valid_from, max(cint(reward.voucher_validity_days), 1))
	if reward.reward_type == "Free Item":
		discount_type, amount, cap = "Flat Amount", _free_item_value(reward.free_item), None
		if amount <= 0:
			frappe.throw(_("Item {0} has no selling price for a free-item voucher.").format(reward.free_item))
	else:
		discount_type, amount = reward.discount_type or "Flat Amount", flt(reward.discount_value)
		cap = flt(reward.max_discount_amount) if discount_type == "Percentage" and flt(reward.max_discount_amount) else None

	code = generate_unique_coupon_code(VOUCHER_PREFIX)
	email = frappe.db.get_value("Customer", account.customer, "email_id") or (
		frappe.db.get_value("User", account.user, "email") if account.user else None
	)
	coupon = frappe.get_doc(
		{
			"doctype": "Coupon Code",
			"name": code,
			"coupon_name": code,
			"coupon_code": code,
			"coupon_type": PROMOTIONAL_COUPON_TYPE,
			"pricing_rule": _pricing_rule(),
			"description": _("Loyalty reward: {0}").format(reward.reward_name),
			"valid_from": valid_from,
			"valid_upto": valid_upto,
			"maximum_use": 1,
			"used": 0,
			"custom_discount_type": discount_type,
			"custom_discount_amount": amount,
			"custom_disc_upto_amount": cap,
			"custom_minimum_subtotal": flt(reward.min_order_amount) or None,
			"custom_redeemption_allow_on": reward.redemption_allow_on or "All",
			"custom_created_on": now_datetime(),
			"custom_linked_email": email,
			"custom_status": COUPON_STATUS_ACTIVE,
			"custom_loyalty_reward": reward.name,
			"custom_loyalty_free_item": reward.free_item if reward.reward_type == "Free Item" else None,
		}
	)
	coupon.insert(ignore_permissions=True)
	return frappe._dict(name=coupon.name, valid_upto=valid_upto, email=email)


def _voucher_result(txn_name: str) -> dict:
	txn = frappe.db.get_value(TXN, txn_name, ["source_name", "reward", "points"], as_dict=True)
	coupon = (
		frappe.db.get_value("Coupon Code", txn.source_name, ["coupon_code", "valid_upto", "custom_status"], as_dict=True)
		or {}
	)
	return {
		"transaction": txn_name,
		"reward": txn.reward,
		"points": -cint(txn.points),
		"coupon_code": coupon.get("coupon_code") or txn.source_name,
		"valid_upto": coupon.get("valid_upto"),
		"status": coupon.get("custom_status"),
	}


def redeem_reward(account_name: str, reward_name: str, request_id: str) -> dict:
	"""Spend points on a reward. Replaying the same request id returns the same voucher.

	The key carries the account: request ids are client-chosen, and a global
	key would hand one member's voucher to another member who reused an id.
	"""
	key = f"reward:{account_name}:{request_id}"
	existing = ledger.find_by_key(key)
	if existing:
		return _voucher_result(existing)

	locked = ledger.lock_account(account_name)
	if locked.status != "Active":
		frappe.throw(_("Loyalty account {0} is {1}.").format(account_name, (locked.status or "").lower()))
	# Re-checked under the lock: a concurrent replay may have just finished.
	existing = ledger.find_by_key(key)
	if existing:
		return _voucher_result(existing)

	reward = frappe.get_doc(REWARD, reward_name)
	limited = cint(reward.stock_limit) or cint(reward.per_customer_limit)
	if limited:
		# Two members taking the last unit at once: the second waits here.
		ledger.lock_row(REWARD, reward.name)
	account = frappe.db.get_value(ACCOUNT, account_name, ["name", "customer", "user", "programme", "tier"], as_dict=True)
	reason = refusal(reward, account, for_update=bool(limited))
	if reason:
		frappe.throw(reason)
	# Points an online order is paying with right now are not free to spend.
	holds.assert_spendable(account_name, cint(reward.points_cost))

	savepoint = "arcpos_loyalty_reward"
	frappe.db.savepoint(savepoint)
	try:
		voucher = _issue_voucher(reward, account)
		txn, _created = ledger.post_debit(
			locked,
			"Redeem",
			cint(reward.points_cost),
			key,
			source_doctype="Coupon Code",
			source_name=voucher.name,
			reward=reward.name,
			remarks=reward.reward_name,
		)
	except ledger.InsufficientPoints as exc:
		frappe.db.rollback(save_point=savepoint)
		frappe.throw(str(exc), title=_("Loyalty Points"))

	frappe.db.set_value("Coupon Code", voucher.name, "custom_loyalty_transaction", txn, update_modified=False)
	frappe.db.set_value(REWARD, reward.name, "redeemed_count", _issued(reward.name), update_modified=False)
	ledger.recompute_cache(account_name, touch_activity=True)

	from excel_restaurant_pos.shared.loyalty.notifications import enqueue_notification

	enqueue_notification(
		account_name,
		"voucher",
		key=f"voucher:{voucher.name}",
		context={"coupon_code": voucher.name, "valid_upto": str(voucher.valid_upto), "reward_name": reward.reward_name},
	)
	return _voucher_result(txn)


# ---------------------------------------------------------------- hooks


def on_voucher_status_change(doc, method=None):
	"""Coupon Code on_update: an unused reward voucher that expired gives its points back.

	Guarded: the coupon expiry job saves coupons in a loop, and a loyalty
	failure here must not stop every later coupon from expiring.
	"""
	ledger.safely("Loyalty voucher refund failed", _refund_expired_voucher, doc)


def _refund_expired_voucher(doc):
	txn = doc.get("custom_loyalty_transaction")
	if not txn or doc.get("custom_status") != COUPON_STATUS_EXPIRED or cint(doc.get("used")):
		return
	before = doc.get_doc_before_save()
	if before and before.get("custom_status") == COUPON_STATUS_EXPIRED:
		return
	settings = get_settings()
	if not settings or not cint(settings.refund_expired_vouchers):
		return

	account = frappe.db.get_value(TXN, txn, "account")
	if not account:
		return
	ledger.lock_account(account)
	ledger.restore_debit(
		account,
		txn,
		f"reverse:{txn}:voucher-expired",
		source_doctype="Coupon Code",
		source_name=doc.name,
		remarks=_("Unused reward voucher {0} expired").format(doc.name),
	)
	ledger.recompute_cache(account)


def validate_free_item_vouchers(doc, method=None):
	"""Sales Invoice validate: a free-item voucher only applies when that item is ordered."""
	code = resolve_applied_coupon_code(doc)
	if not code or not frappe.get_meta("Coupon Code").has_field("custom_loyalty_free_item"):
		return
	item = frappe.db.get_value("Coupon Code", code, "custom_loyalty_free_item")
	if item and item not in {row.item_code for row in doc.get("items") or []}:
		frappe.throw(
			_("Voucher {0} is for a free {1}. Add it to the order first.").format(
				code, frappe.db.get_value("Item", item, "item_name") or item
			)
		)
