# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	summary = [
		{
			"value": sum(flt(r.get("redeemed_amount")) for r in data),
			"label": _("Total Redeemed"),
			"datatype": "Currency",
		},
		{"value": len(data), "label": _("Redemptions"), "datatype": "Int"},
	]
	return columns, data, None, None, summary


def get_columns():
	return [
		{
			"label": _("Gift Card"),
			"fieldname": "gift_card",
			"fieldtype": "Link",
			"options": "Coupon Code",
			"width": 160,
		},
		{
			"label": _("Sales Invoice"),
			"fieldname": "sales_invoice",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{
			"label": _("Redeemed Amount"),
			"fieldname": "redeemed_amount",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Invoice Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("Card Status"),
			"fieldname": "custom_status",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Remaining Balance"),
			"fieldname": "custom_available_balance",
			"fieldtype": "Currency",
			"width": 140,
		},
		{
			"label": _("Email"),
			"fieldname": "custom_linked_email",
			"fieldtype": "Data",
			"width": 180,
		},
	]


def get_data(filters):
	conditions = ["cc.coupon_type = 'Gift Card'"]
	values = {}

	if filters.get("gift_card"):
		conditions.append("cc.name = %(gift_card)s")
		values["gift_card"] = filters.get("gift_card")

	if filters.get("sales_invoice"):
		conditions.append("r.sales_invoice = %(sales_invoice)s")
		values["sales_invoice"] = filters.get("sales_invoice")

	if filters.get("from_date"):
		conditions.append("si.posting_date >= %(from_date)s")
		values["from_date"] = getdate(filters.get("from_date"))

	if filters.get("to_date"):
		conditions.append("si.posting_date <= %(to_date)s")
		values["to_date"] = getdate(filters.get("to_date"))

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT
			cc.name AS gift_card,
			r.sales_invoice,
			r.redeemed_amount,
			si.posting_date,
			cc.custom_status,
			cc.custom_available_balance,
			cc.custom_linked_email
		FROM `tabCoupon Redeemed on Orders` r
		INNER JOIN `tabCoupon Code` cc ON cc.name = r.parent
		LEFT JOIN `tabSales Invoice` si ON si.name = r.sales_invoice
		WHERE {where}
		ORDER BY si.posting_date DESC, r.creation DESC
		""",
		values,
		as_dict=True,
	)
