# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_months, cint, getdate, nowdate

TXN = "ArcPOS Loyalty Transaction"

CHANNEL_SQL = """
	CASE
		WHEN LOWER(si.custom_order_from) = 'table' THEN 'dine_in'
		WHEN LOWER(si.custom_order_from) = 'in store' AND LOWER(si.custom_service_type) = 'pickup' THEN 'in_store_pickup'
		WHEN LOWER(si.custom_order_from) = 'website' AND LOWER(si.custom_service_type) = 'delivery' THEN 'online_delivery'
		WHEN LOWER(si.custom_order_from) = 'website' AND LOWER(si.custom_service_type) = 'pickup' THEN 'online_pickup'
		WHEN si.name IS NULL THEN 'non_order'
		ELSE 'other'
	END
"""

GROUPS = {
	"Month": "DATE_FORMAT(t.posting_datetime, '%%Y-%%m')",
	"Week": "DATE_FORMAT(t.posting_datetime, '%%x-W%%v')",
	"Day": "DATE(t.posting_datetime)",
	"Campaign": "IFNULL(t.campaign, 'Base / none')",
	"Channel": CHANNEL_SQL,
	"Type": "t.transaction_type",
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	group_by = filters.get("group_by") or "Month"
	data = get_data(filters, group_by)
	return get_columns(group_by), data, None, get_chart(data, group_by)


def get_columns(group_by):
	return [
		{"label": _(group_by), "fieldname": "period", "fieldtype": "Data", "width": 160},
		{"label": _("Earned"), "fieldname": "earned", "fieldtype": "Int", "width": 110},
		{"label": _("Bonus"), "fieldname": "bonus", "fieldtype": "Int", "width": 110},
		{"label": _("Redeemed"), "fieldname": "redeemed", "fieldtype": "Int", "width": 110},
		{"label": _("Expired"), "fieldname": "expired", "fieldtype": "Int", "width": 110},
		{"label": _("Reversed (net)"), "fieldname": "reversed", "fieldtype": "Int", "width": 120},
		{"label": _("Adjusted (net)"), "fieldname": "adjusted", "fieldtype": "Int", "width": 120},
		{"label": _("Net Change"), "fieldname": "net", "fieldtype": "Int", "width": 110},
		{"label": _("Net Value"), "fieldname": "value", "fieldtype": "Currency", "width": 120},
	]


def get_data(filters, group_by):
	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -12))
	to_date = getdate(filters.get("to_date") or nowdate())
	conditions = ["t.posting_datetime BETWEEN %(from)s AND %(to)s"]
	values = {"from": f"{from_date} 00:00:00", "to": f"{to_date} 23:59:59"}
	for field in ("programme", "campaign"):
		if filters.get(field):
			conditions.append(f"t.{field} = %({field})s")
			values[field] = filters.get(field)
	if filters.get("channel"):
		conditions.append(f"({CHANNEL_SQL}) = %(channel)s")
		values["channel"] = filters.channel

	rows = frappe.db.sql(
		f"""
		SELECT
			{GROUPS.get(group_by, GROUPS["Month"])} AS period,
			SUM(CASE WHEN t.transaction_type = 'Earn' THEN t.points ELSE 0 END) AS earned,
			SUM(CASE WHEN t.transaction_type = 'Bonus' THEN t.points ELSE 0 END) AS bonus,
			-SUM(CASE WHEN t.transaction_type = 'Redeem' THEN t.points ELSE 0 END) AS redeemed,
			-SUM(CASE WHEN t.transaction_type = 'Expire' THEN t.points ELSE 0 END) AS expired,
			SUM(CASE WHEN t.transaction_type = 'Reverse' THEN t.points ELSE 0 END) AS reversed,
			SUM(CASE WHEN t.transaction_type = 'Adjust' THEN t.points ELSE 0 END) AS adjusted,
			SUM(t.points) AS net,
			SUM(t.currency_value) AS value
		FROM `tab{TXN}` t
		LEFT JOIN `tabSales Invoice` si ON t.source_doctype = 'Sales Invoice' AND si.name = t.source_name
		WHERE {" AND ".join(conditions)}
		GROUP BY period
		ORDER BY period
		""",
		values,
		as_dict=True,
	)
	for row in rows:
		for key in ("earned", "bonus", "redeemed", "expired", "reversed", "adjusted", "net"):
			row[key] = cint(row[key])
	return rows


def get_chart(data, group_by):
	if not data or group_by not in ("Month", "Week", "Day"):
		return None
	return {
		"data": {
			"labels": [str(r.period) for r in data],
			"datasets": [
				{"name": _("Earned + Bonus"), "values": [r.earned + r.bonus for r in data]},
				{"name": _("Redeemed"), "values": [r.redeemed for r in data]},
				{"name": _("Expired"), "values": [r.expired for r in data]},
			],
		},
		"type": "line",
	}
