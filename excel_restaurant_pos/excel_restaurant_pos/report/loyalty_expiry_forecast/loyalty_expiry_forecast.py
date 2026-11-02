# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, nowdate

from excel_restaurant_pos.shared.loyalty.settings import get_programme, get_settings

TXN = "ArcPOS Loyalty Transaction"
PERIODS = {"Weekly": "DATE_FORMAT(expiry_date, '%%x-W%%v')", "Monthly": "DATE_FORMAT(expiry_date, '%%Y-%%m')"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	settings = get_settings()
	programme = get_programme(filters.get("programme") or (settings.active_programme if settings else None))
	if not programme:
		return get_columns(), [], _("Choose a programme.")
	data = get_data(filters, programme)
	chart = {
		"data": {"labels": [r.period for r in data], "datasets": [{"name": _("Points expiring"), "values": [r.points for r in data]}]},
		"type": "bar",
	} if data else None
	return get_columns(), data, None, chart


def get_columns():
	return [
		{"label": _("Period"), "fieldname": "period", "fieldtype": "Data", "width": 120},
		{"label": _("Points Expiring"), "fieldname": "points", "fieldtype": "Int", "width": 130},
		{"label": _("Value"), "fieldname": "value", "fieldtype": "Currency", "width": 130},
		{"label": _("Members"), "fieldname": "members", "fieldtype": "Int", "width": 100},
	]


def get_data(filters, programme):
	period = PERIODS.get(filters.get("period") or "Monthly", PERIODS["Monthly"])
	horizon = add_months(nowdate(), cint(filters.get("horizon_months")) or 12)
	rows = frappe.db.sql(
		f"""
		SELECT {period} AS period, SUM(remaining_points) AS points, COUNT(DISTINCT account) AS members
		FROM `tab{TXN}`
		WHERE programme = %(programme)s AND points > 0 AND status = 'Available' AND remaining_points > 0
			AND expiry_date BETWEEN %(today)s AND %(horizon)s
		GROUP BY period
		ORDER BY period
		""",
		{"programme": programme.name, "today": nowdate(), "horizon": horizon},
		as_dict=True,
	)
	for row in rows:
		row["points"] = cint(row.points)
		row["value"] = flt(row.points * flt(programme.point_value), 2)
	return rows
