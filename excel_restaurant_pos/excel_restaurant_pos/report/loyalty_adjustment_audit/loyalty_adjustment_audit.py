# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_months, getdate, nowdate

ADJUSTMENT = "ArcPOS Loyalty Adjustment"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Adjustment"), "fieldname": "name", "fieldtype": "Link", "options": ADJUSTMENT, "width": 140},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Member"), "fieldname": "account", "fieldtype": "Link", "options": "ArcPOS Loyalty Account", "width": 120},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 160},
		{"label": _("Points"), "fieldname": "points", "fieldtype": "Int", "width": 90},
		{"label": _("Reason"), "fieldname": "reason", "fieldtype": "Data", "width": 110},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 220},
		{"label": _("Status"), "fieldname": "approval_status", "fieldtype": "Data", "width": 120},
		{"label": _("Posted"), "fieldname": "docstatus", "fieldtype": "Int", "width": 70},
		{"label": _("Requested By"), "fieldname": "requested_by", "fieldtype": "Link", "options": "User", "width": 150},
		{"label": _("Decided By"), "fieldname": "approved_by", "fieldtype": "Link", "options": "User", "width": 150},
		{"label": _("Decided On"), "fieldname": "approved_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Ledger Entry"), "fieldname": "transaction", "fieldtype": "Link", "options": "ArcPOS Loyalty Transaction", "width": 150},
	]


def get_data(filters):
	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -3))
	to_date = getdate(filters.get("to_date") or nowdate())
	conditions = {"posting_date": ["between", [from_date, to_date]]}
	for field in ("approval_status", "account", "reason"):
		if filters.get(field):
			conditions[field] = filters.get(field)
	return frappe.get_all(
		ADJUSTMENT,
		filters=conditions,
		fields=[c["fieldname"] for c in get_columns()],
		order_by="posting_date desc, creation desc",
	)
