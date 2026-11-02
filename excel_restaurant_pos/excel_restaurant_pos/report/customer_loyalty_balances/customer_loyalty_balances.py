# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint

ACCOUNT = "ArcPOS Loyalty Account"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Member"), "fieldname": "name", "fieldtype": "Link", "options": ACCOUNT, "width": 130},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 140},
		{"label": _("Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 170},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Tier"), "fieldname": "tier", "fieldtype": "Data", "width": 90},
		{"label": _("Available"), "fieldname": "available_points", "fieldtype": "Int", "width": 100},
		{"label": _("Pending"), "fieldname": "pending_points", "fieldtype": "Int", "width": 90},
		{"label": _("Next Expiry"), "fieldname": "next_expiry_date", "fieldtype": "Date", "width": 110},
		{"label": _("Expiring"), "fieldname": "next_expiry_points", "fieldtype": "Int", "width": 90},
		{"label": _("Lifetime Earned"), "fieldname": "lifetime_earned", "fieldtype": "Int", "width": 120},
		{"label": _("Lifetime Redeemed"), "fieldname": "lifetime_redeemed", "fieldtype": "Int", "width": 130},
		{"label": _("Lifetime Expired"), "fieldname": "lifetime_expired", "fieldtype": "Int", "width": 120},
		{"label": _("Orders"), "fieldname": "order_count", "fieldtype": "Int", "width": 80},
		{"label": _("Last Activity"), "fieldname": "last_activity_at", "fieldtype": "Datetime", "width": 150},
	]


def get_data(filters):
	conditions = {field: filters.get(field) for field in ("programme", "status", "tier") if filters.get(field)}
	if cint(filters.get("min_points")):
		conditions["available_points"] = [">=", cint(filters.min_points)]
	return frappe.get_all(
		ACCOUNT,
		filters=conditions,
		fields=[c["fieldname"] for c in get_columns()],
		order_by="available_points desc",
		limit_page_length=cint(filters.get("limit")) or 5000,
	)
