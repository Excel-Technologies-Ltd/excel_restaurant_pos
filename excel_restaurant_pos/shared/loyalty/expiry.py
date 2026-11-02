"""Scheduled lot lifecycle: release pending points, expire points, warn before expiry."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, nowdate

from excel_restaurant_pos.shared.loyalty import ledger
from excel_restaurant_pos.shared.loyalty.notifications import enqueue_notification
from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, PROGRAMME, TXN, is_enabled

FIXED, ROLLING, NEVER = "Fixed Days per Lot", "Rolling Inactivity", "Never"
OPEN_LOT = {"points": [">", 0], "status": ["in", ["Pending", "Available"]], "remaining_points": [">", 0]}


def _programmes() -> list:
	"""Every programme holding balances: a paused or ended one still expires its points."""
	names = frappe.get_all(PROGRAMME, filters={"status": ["!=", "Draft"]}, pluck="name")
	return [frappe.get_cached_doc(PROGRAMME, name) for name in names]


def release_pending_points():
	"""Hourly: Pending lots whose return window has passed become spendable."""
	if not is_enabled():
		return
	accounts = frappe.get_all(
		TXN,
		filters={"status": "Pending", "available_on": ["<=", getdate(nowdate())], "points": [">", 0]},
		pluck="account",
		distinct=True,
	)
	# Account by account, each committed on its own: one failure must not
	# leave every other member's points unreleased, run after run.
	for account in accounts:
		ledger.safely("Loyalty pending release failed", _release_account, account)
		frappe.db.commit()


def _release_account(account: str):
	ledger.lock_account(account)
	if ledger.release_pending(account):
		ledger.recompute_cache(account)
		enqueue_notification(account, "available", key=f"available:{account}:{nowdate()}", context={})


def _expire_lots(account: str, lots: list[str], suffix: str = "", remarks: str | None = None):
	ledger.safely("Loyalty point expiry failed", _expire_account_lots, account, lots, suffix, remarks)


def _expire_account_lots(account: str, lots: list[str], suffix: str, remarks: str | None):
	ledger.lock_account(account)
	for lot in lots:
		ledger.expire_lot(account, lot, f"expire:{lot}{suffix}", remarks=remarks)
	ledger.recompute_cache(account)


def expire_points():
	"""Daily 00:30: lots past their expiry date, or every lot of an inactive member."""
	if not is_enabled():
		return
	today = getdate(nowdate())
	for programme in _programmes():
		if programme.expiry_mode == FIXED:
			rows = frappe.get_all(
				TXN,
				filters={"programme": programme.name, "expiry_date": ["<", today], **OPEN_LOT},
				fields=["name", "account"],
				order_by="account",
			)
			by_account: dict[str, list[str]] = {}
			for row in rows:
				by_account.setdefault(row.account, []).append(row.name)
			for account, lots in by_account.items():
				_expire_lots(account, lots)
				frappe.db.commit()

		elif programme.expiry_mode == ROLLING and cint(programme.expiry_days) > 0:
			cutoff = add_days(today, -cint(programme.expiry_days))
			# A member with points but no recorded activity (credited only by an
			# adjustment or an event) counts as inactive since enrolment.
			accounts = frappe.db.sql(
				f"""
				SELECT name FROM `tab{ACCOUNT}`
				WHERE programme = %(programme)s AND available_points > 0
					AND COALESCE(last_activity_at, enrolled_on, creation) < %(cutoff)s
				""",
				{"programme": programme.name, "cutoff": cutoff},
				pluck=True,
			)
			remarks = _("No activity for {0} days").format(programme.expiry_days)
			for account in accounts:
				lots = frappe.get_all(TXN, filters={"account": account, **OPEN_LOT}, pluck="name")
				_expire_lots(account, lots, suffix=f":inactive:{today}", remarks=remarks)
				frappe.db.commit()


def notice_offsets(programme) -> list[int]:
	offsets = {int(part) for part in (programme.expiry_notice_days or "").split(",") if part.strip().isdigit()}
	return sorted((d for d in offsets if d > 0), reverse=True)


def send_expiry_notices():
	"""Daily 09:00: members with points expiring N days from now, once per offset."""
	if not is_enabled():
		return
	today = getdate(nowdate())
	for programme in _programmes():
		if programme.status != "Active" or programme.expiry_mode == NEVER:
			continue
		for days in notice_offsets(programme):
			target = add_days(today, days)
			if programme.expiry_mode == FIXED:
				rows = frappe.db.sql(
					f"""
					SELECT account, SUM(remaining_points) AS points
					FROM `tab{TXN}`
					WHERE programme = %s AND points > 0 AND status = 'Available'
						AND remaining_points > 0 AND expiry_date = %s
					GROUP BY account
					""",
					(programme.name, target),
					as_dict=True,
				)
			else:
				rows = frappe.db.sql(
					f"""
					SELECT name AS account, available_points AS points
					FROM `tab{ACCOUNT}`
					WHERE programme = %s AND status = 'Active' AND available_points > 0
						AND DATE(last_activity_at) = %s
					""",
					(programme.name, add_days(target, -cint(programme.expiry_days))),
					as_dict=True,
				)
			for row in rows:
				enqueue_notification(
					row.account,
					"expiring",
					key=f"expiring:{row.account}:{target}:{days}",
					context={"points": cint(row.points), "expiry_date": str(target), "days": days},
				)
	frappe.db.commit()
