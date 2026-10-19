"""Membership tiers: qualification, upgrades, review-date downgrades, history."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, TIER_CHANGE, TXN, get_programme

CONTINUOUS = "Continuous"
REVIEW_PERIOD_DAYS = 365


def tiers_of(programme) -> list:
	return sorted(programme.get("tiers") or [], key=lambda t: cint(t.rank))


def lowest_tier(programme):
	tiers = tiers_of(programme) if programme else []
	return tiers[0] if tiers else None


def tier_named(programme, name):
	return next((t for t in tiers_of(programme) if t.tier_name == name), None)


def tier_for_value(programme, value: float):
	"""The highest-ranked tier whose threshold `value` meets (the lowest tier otherwise)."""
	tiers = tiers_of(programme)
	if not tiers:
		return None
	qualified = [t for t in tiers if flt(value) >= flt(t.threshold)]
	return qualified[-1] if qualified else tiers[0]


def next_tier(programme, current_name):
	tiers = tiers_of(programme)
	current = tier_named(programme, current_name)
	if not current:
		return tiers[0] if tiers else None
	higher = [t for t in tiers if cint(t.rank) > cint(current.rank)]
	return higher[0] if higher else None


def multiplier_for(programme, tier_name) -> float:
	tier = tier_named(programme, tier_name) if programme and tier_name else None
	return flt(tier.earn_multiplier) if tier and flt(tier.earn_multiplier) > 0 else 1.0


def qualifying_value(account, programme) -> float:
	basis = programme.tier_basis or "Lifetime Spend"
	if basis == "Rolling 12-Month Points":
		since = add_days(now_datetime(), -REVIEW_PERIOD_DAYS)
		row = frappe.db.sql(
			f"""
			SELECT COALESCE(SUM(t.points), 0)
			FROM `tab{TXN}` t
			LEFT JOIN `tab{TXN}` r ON r.name = t.reverses
			WHERE t.account = %s AND t.posting_datetime >= %s
				AND (t.transaction_type IN ('Earn', 'Bonus')
					OR (t.transaction_type = 'Reverse' AND t.points < 0 AND r.transaction_type IN ('Earn', 'Bonus')))
			""",
			(account.name, since),
		)
		return flt(row[0][0])

	conditions = "customer = %s AND docstatus = 1"
	values = [account.customer]
	if basis == "Rolling 12-Month Spend":
		conditions += " AND posting_date >= %s"
		values.append(add_days(nowdate(), -REVIEW_PERIOD_DAYS))
	# Credit notes carry a negative net total, so returns reduce the spend.
	row = frappe.db.sql(f"SELECT COALESCE(SUM(base_net_total), 0) FROM `tabSales Invoice` WHERE {conditions}", values)
	return flt(row[0][0])


def evaluate(account_name: str, reason: str = "", review: bool = False) -> str | None:
	"""Recompute an account's tier. Returns the new tier when it changed.

	Upgrades apply at once. Downgrades wait for the review date unless the
	programme reviews continuously; `review=True` is the scheduled review.
	"""
	account = frappe.db.get_value(
		ACCOUNT,
		account_name,
		["name", "customer", "programme", "tier", "tier_review_date", "status"],
		as_dict=True,
	)
	if not account:
		return None
	programme = get_programme(account.programme)
	if not programme or not programme.get("tiers"):
		return None

	value = qualifying_value(account, programme)
	frappe.db.set_value(ACCOUNT, account.name, "qualifying_value", value, update_modified=False)

	target = tier_for_value(programme, value)
	current = tier_named(programme, account.tier)
	if not target or (current and target.tier_name == current.tier_name):
		# A review that keeps the tier starts the next review period. Left in
		# the past, the date would stay "due" and the very next dip below the
		# threshold would downgrade at once instead of at the next review.
		due = account.tier_review_date and getdate(account.tier_review_date) <= getdate(nowdate())
		if review and due and current:
			frappe.db.set_value(
				ACCOUNT,
				account.name,
				"tier_review_date",
				add_days(nowdate(), REVIEW_PERIOD_DAYS),
				update_modified=False,
			)
		return None

	if current and cint(target.rank) < cint(current.rank):
		due = account.tier_review_date and getdate(account.tier_review_date) <= getdate(nowdate())
		if programme.tier_review != CONTINUOUS and not (review and due):
			return None

	change_tier(account, current.tier_name if current else None, target.tier_name, value, reason)
	return target.tier_name


def change_tier(account, from_tier, to_tier, value, reason=""):
	today = nowdate()
	frappe.db.set_value(
		ACCOUNT,
		account.name,
		{"tier": to_tier, "tier_since": today, "tier_review_date": add_days(today, REVIEW_PERIOD_DAYS)},
		update_modified=False,
	)
	frappe.get_doc(
		{
			"doctype": TIER_CHANGE,
			"account": account.name,
			"customer": account.customer,
			"from_tier": from_tier,
			"to_tier": to_tier,
			"reason": (reason or "")[:140],
			"qualifying_value": value,
			"changed_at": now_datetime(),
		}
	).insert(ignore_permissions=True)

	from excel_restaurant_pos.shared.loyalty.notifications import enqueue_notification
	from excel_restaurant_pos.shared.loyalty.wallet.sync import schedule_sync

	enqueue_notification(
		account.name,
		"tier_change",
		key=f"tier:{account.name}:{to_tier}:{today}",
		context={"from_tier": from_tier, "to_tier": to_tier},
	)
	schedule_sync(account.name)


def progress(account, programme) -> dict:
	"""Next-tier progress for the app."""
	nxt = next_tier(programme, account.tier)
	value = flt(account.qualifying_value)
	if not nxt:
		return {"next_tier": None, "threshold": None, "remaining": 0, "basis": programme.tier_basis}
	return {
		"next_tier": nxt.tier_name,
		"threshold": flt(nxt.threshold),
		"remaining": max(flt(nxt.threshold) - value, 0),
		"basis": programme.tier_basis,
	}


def review_tiers():
	"""Daily: rolling-window recalculation and downgrades at review date."""
	from excel_restaurant_pos.shared.loyalty.settings import get_active_programme

	programme = get_active_programme()
	if not programme or not programme.get("tiers"):
		return
	accounts = frappe.get_all(ACCOUNT, filters={"programme": programme.name, "status": "Active"}, pluck="name")
	from excel_restaurant_pos.shared.loyalty.ledger import safely

	for index, name in enumerate(accounts, 1):
		# A savepoint per account: a failure half way through a tier change
		# must not leave the tier set without its Tier Change record.
		safely("Loyalty tier review failed", evaluate, name, reason=_("Scheduled tier review"), review=True)
		if index % 200 == 0:
			frappe.db.commit()
	frappe.db.commit()
