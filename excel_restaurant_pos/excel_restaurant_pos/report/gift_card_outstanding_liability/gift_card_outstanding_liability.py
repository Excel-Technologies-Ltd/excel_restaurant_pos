# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	summary = get_summary(data)
	return columns, data, None, None, summary


def get_columns():
	return [
		{
			"label": _("Gift Card"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Coupon Code",
			"width": 160,
		},
		{
			"label": _("Status"),
			"fieldname": "custom_status",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Face Value"),
			"fieldname": "custom_discount_amount",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Available Balance"),
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
		{
			"label": _("Sold On Invoice"),
			"fieldname": "custom_generated_on_order",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{
			"label": _("Valid From"),
			"fieldname": "valid_from",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("Valid Upto"),
			"fieldname": "valid_upto",
			"fieldtype": "Date",
			"width": 110,
		},
	]


def get_data(filters):
	status_filters = filters.get("status")
	query_filters = {"coupon_type": "Gift Card"}
	if status_filters:
		query_filters["custom_status"] = status_filters
	else:
		# Outstanding = Active with remaining balance (Inactive stock is inventory, not liability yet)
		query_filters["custom_status"] = "Active"

	rows = frappe.get_all(
		"Coupon Code",
		filters=query_filters,
		fields=[
			"name",
			"coupon_code",
			"custom_status",
			"custom_discount_amount",
			"custom_available_balance",
			"custom_linked_email",
			"custom_generated_on_order",
			"valid_from",
			"valid_upto",
		],
		order_by="custom_available_balance desc, name asc",
	)

	# Only cards with positive remaining balance for liability view
	if not status_filters:
		rows = [r for r in rows if flt(r.custom_available_balance) > 0]

	if filters.get("email"):
		term = filters.get("email").strip().lower()
		rows = [r for r in rows if term in (r.custom_linked_email or "").lower()]

	return rows


def get_summary(data):
	total_face = sum(flt(r.get("custom_discount_amount")) for r in data)
	total_balance = sum(flt(r.get("custom_available_balance")) for r in data)
	return [
		{"value": len(data), "label": _("Cards"), "datatype": "Int"},
		{"value": total_face, "label": _("Face Value Total"), "datatype": "Currency"},
		{"value": total_balance, "label": _("Outstanding Balance"), "datatype": "Currency"},
	]
