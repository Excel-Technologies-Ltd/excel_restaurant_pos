# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from excel_restaurant_pos.shared.loyalty.accounting import gl_balance, outstanding_points
from excel_restaurant_pos.shared.loyalty.settings import get_programme, get_settings

TXN = "ArcPOS Loyalty Transaction"
BUCKETS = (
	("Expires in 0-30 days", 0, 30),
	("Expires in 31-90 days", 31, 90),
	("Expires in 91-180 days", 91, 180),
	("Expires in over 180 days", 181, None),
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	settings = get_settings()
	programme = get_programme(filters.get("programme") or (settings.active_programme if settings else None))
	if not programme:
		return get_columns(), [], _("Choose a programme.")
	return get_columns(), get_data(programme), None, None, get_summary(programme, settings)


def get_columns():
	return [
		{"label": _("Bucket"), "fieldname": "bucket", "fieldtype": "Data", "width": 220},
		{"label": _("Points"), "fieldname": "points", "fieldtype": "Int", "width": 120},
		{"label": _("Value"), "fieldname": "value", "fieldtype": "Currency", "width": 140},
		{"label": _("Lots"), "fieldname": "lots", "fieldtype": "Int", "width": 90},
		{"label": _("Members"), "fieldname": "members", "fieldtype": "Int", "width": 100},
	]


def _row(label, programme, condition, values=None):
	row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(remaining_points), 0) AS points, COUNT(*) AS lots, COUNT(DISTINCT account) AS members
		FROM `tab{TXN}`
		WHERE programme = %(programme)s AND points > 0 AND remaining_points > 0 AND {condition}
		""",
		{"programme": programme.name, "today": nowdate(), **(values or {})},
		as_dict=True,
	)[0]
	return {
		"bucket": _(label),
		"points": cint(row.points),
		"value": flt(cint(row.points) * flt(programme.point_value), 2),
		"lots": cint(row.lots),
		"members": cint(row.members),
	}


def get_data(programme):
	rows = []
	for label, start, end in BUCKETS:
		condition = "status = 'Available' AND DATEDIFF(expiry_date, %(today)s) >= %(start)s"
		values = {"start": start}
		if end is not None:
			condition += " AND DATEDIFF(expiry_date, %(today)s) <= %(end)s"
			values["end"] = end
		rows.append(_row(label, programme, condition, values))
	rows.append(_row("No expiry", programme, "status = 'Available' AND expiry_date IS NULL"))
	rows.append(_row("Pending (not yet spendable)", programme, "status = 'Pending'"))

	debt = cint(
		frappe.db.sql(
			f"SELECT COALESCE(SUM(outstanding_debt), 0) FROM `tab{TXN}` WHERE programme = %s AND points < 0",
			programme.name,
		)[0][0]
	)
	if debt:
		rows.append({"bucket": _("Negative balances owed"), "points": -debt, "value": -flt(debt * flt(programme.point_value), 2)})
	return rows


def get_summary(programme, settings):
	points = outstanding_points(programme.name)
	target = flt(points * flt(programme.point_value), 2)
	summary = [
		{"label": _("Outstanding Points"), "value": points, "datatype": "Int"},
		{"label": _("Liability (ledger)"), "value": target, "datatype": "Currency"},
	]
	if settings and settings.liability_account:
		balance = flt(gl_balance(settings.liability_account, programme.company), 2)
		summary += [
			{"label": _("Liability (GL)"), "value": balance, "datatype": "Currency"},
			{
				"label": _("Difference"),
				"value": flt(target - balance, 2),
				"datatype": "Currency",
				"indicator": "Green" if abs(target - balance) < 0.01 else "Red",
			},
		]
	return summary
