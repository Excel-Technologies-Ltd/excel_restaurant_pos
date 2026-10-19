"""Loyalty liability accounting: a periodic true-up Journal Entry.

Earning does not post to the GL one entry at a time (thousands a day).
Instead the GL liability is moved to match the ledger on each run:

	target  = (available + pending points) x point value
	balance = credit - debit on the liability account
	delta   = target - balance  -> Dr Expense / Cr Liability (or the reverse)

Redemption tender already debits the liability through its Payment Entry,
and expired points simply leave the target, so breakage flows out at the next
run.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, get_last_day, getdate, nowdate

from excel_restaurant_pos.shared.loyalty.settings import LIABILITY_RUN, TXN, get_programme, get_settings, is_enabled


def outstanding_points(programme: str) -> int:
	row = frappe.db.sql(
		f"""
		SELECT
			COALESCE(SUM(CASE WHEN points > 0 AND status IN ('Available', 'Pending') THEN remaining_points ELSE 0 END), 0)
			- COALESCE(SUM(CASE WHEN points < 0 THEN outstanding_debt ELSE 0 END), 0)
		FROM `tab{TXN}`
		WHERE programme = %s
		""",
		programme,
	)
	return cint(row[0][0])


def gl_balance(account: str, company: str, upto=None) -> float:
	conditions, values = "account = %s AND company = %s AND is_cancelled = 0", [account, company]
	if upto:
		conditions += " AND posting_date <= %s"
		values.append(upto)
	row = frappe.db.sql(f"SELECT COALESCE(SUM(credit - debit), 0) FROM `tabGL Entry` WHERE {conditions}", values)
	return flt(row[0][0])


def _log(programme, status, **values):
	return frappe.get_doc(
		{
			"doctype": LIABILITY_RUN,
			"run_date": nowdate(),
			"company": programme.company if programme else None,
			"programme": programme.name if programme else None,
			"status": status,
			**values,
		}
	).insert(ignore_permissions=True)


def post_liability_true_up(force: bool = False):
	"""Scheduled daily at 23:50; on Monthly frequency it only acts on the last day of the month."""
	if not is_enabled():
		return None
	settings = get_settings()
	frequency = settings.liability_true_up_frequency or "Daily"
	if not force:
		if frequency == "Off":
			return None
		if frequency == "Monthly" and getdate(nowdate()) != getdate(get_last_day(nowdate())):
			return None

	programme = get_programme(settings.active_programme)
	if not programme:
		return None
	if not settings.liability_account or not settings.expense_account:
		run = _log(programme, "Skipped", remarks=_("Set the liability and expense accounts in ArcPOS Loyalty Settings."))
		frappe.db.commit()
		return run.name

	points = outstanding_points(programme.name)
	target = flt(points * flt(programme.point_value), 2)
	balance = flt(gl_balance(settings.liability_account, programme.company), 2)
	delta = flt(target - balance, 2)
	values = {"outstanding_points": points, "target_value": target, "gl_balance": balance, "delta": delta}

	if abs(delta) < 0.01:
		run = _log(programme, "No Change", **values)
		frappe.db.commit()
		return run.name

	cost_center = settings.cost_center or frappe.get_cached_value("Company", programme.company, "cost_center")
	amount = abs(delta)
	if delta > 0:
		debit_account, credit_account = settings.expense_account, settings.liability_account
	else:
		debit_account, credit_account = settings.liability_account, settings.expense_account

	savepoint = "arcpos_loyalty_true_up"
	frappe.db.savepoint(savepoint)
	try:
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.company = programme.company
		je.posting_date = nowdate()
		je.user_remark = _("Loyalty liability true-up: {0} points outstanding at {1} = {2}").format(
			points, programme.point_value, target
		)
		je.append("accounts", {"account": debit_account, "debit_in_account_currency": amount, "cost_center": cost_center})
		je.append("accounts", {"account": credit_account, "credit_in_account_currency": amount, "cost_center": cost_center})
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		run = _log(programme, "Posted", journal_entry=je.name, **values)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(title="Loyalty liability true-up failed", message=frappe.get_traceback())
		run = _log(programme, "Failed", remarks=frappe.get_traceback()[-1000:], **values)
	frappe.db.commit()
	return run.name
