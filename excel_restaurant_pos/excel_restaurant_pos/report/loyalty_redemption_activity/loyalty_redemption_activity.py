# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_months, cint, getdate, nowdate

from excel_restaurant_pos.excel_restaurant_pos.report.loyalty_points_summary.loyalty_points_summary import CHANNEL_SQL

TXN = "ArcPOS Loyalty Transaction"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Date"), "fieldname": "posting_datetime", "fieldtype": "Datetime", "width": 150},
		{"label": _("Member"), "fieldname": "account", "fieldtype": "Link", "options": "ArcPOS Loyalty Account", "width": 120},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 140},
		{"label": _("Points"), "fieldname": "points", "fieldtype": "Int", "width": 90},
		{"label": _("Value"), "fieldname": "value", "fieldtype": "Currency", "width": 100},
		{"label": _("Restored"), "fieldname": "restored", "fieldtype": "Int", "width": 90},
		{"label": _("Source Type"), "fieldname": "source_doctype", "fieldtype": "Data", "width": 110},
		{"label": _("Order / Voucher"), "fieldname": "source_name", "fieldtype": "Dynamic Link", "options": "source_doctype", "width": 150},
		{"label": _("Reward"), "fieldname": "reward", "fieldtype": "Link", "options": "ArcPOS Loyalty Reward", "width": 140},
		{"label": _("Channel"), "fieldname": "channel", "fieldtype": "Data", "width": 120},
		{"label": _("Outlet"), "fieldname": "territory", "fieldtype": "Link", "options": "Territory", "width": 120},
		{"label": _("Staff"), "fieldname": "staff", "fieldtype": "Link", "options": "User", "width": 150},
	]


def get_data(filters):
	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -1))
	to_date = getdate(filters.get("to_date") or nowdate())
	conditions = ["t.transaction_type = 'Redeem'", "t.posting_datetime BETWEEN %(from)s AND %(to)s"]
	values = {"from": f"{from_date} 00:00:00", "to": f"{to_date} 23:59:59"}
	if filters.get("reward"):
		conditions.append("t.reward = %(reward)s")
		values["reward"] = filters.reward
	if filters.get("territory"):
		conditions.append("si.territory = %(territory)s")
		values["territory"] = filters.territory
	if filters.get("channel"):
		conditions.append(f"({CHANNEL_SQL}) = %(channel)s")
		values["channel"] = filters.channel

	rows = frappe.db.sql(
		f"""
		SELECT
			t.name, t.posting_datetime, t.account, t.customer, -t.points AS points, -t.currency_value AS value,
			t.source_doctype, t.source_name, t.reward, si.territory, si.owner AS staff,
			({CHANNEL_SQL}) AS channel,
			(SELECT COALESCE(SUM(r.points), 0) FROM `tab{TXN}` r WHERE r.reverses = t.name AND r.points > 0) AS restored
		FROM `tab{TXN}` t
		LEFT JOIN `tabSales Invoice` si ON t.source_doctype = 'Sales Invoice' AND si.name = t.source_name
		WHERE {" AND ".join(conditions)}
		ORDER BY t.posting_datetime DESC
		""",
		values,
		as_dict=True,
	)
	for row in rows:
		row["restored"] = cint(row.restored)
		if row.source_doctype != "Sales Invoice":
			row["channel"] = _("Reward catalogue") if row.reward else None
	return rows
