"""Repair stuck Sales Invoice Item.custom_gift_amount Custom Field.

A previous migrate briefly set fieldtype to Currency. The ALTER failed because
existing varchar values cannot cast to decimal, but the Custom Field row was
already saved as Currency. Later fixture sync can skip the revert when the DB
modified timestamp is newer than the fixture, leaving migrate stuck.

Force fieldtype back to Data before fixtures/schema sync.
"""

from __future__ import annotations

import frappe


CUSTOM_FIELD_NAME = "Sales Invoice Item-custom_gift_amount"


def execute():
	if not frappe.db.exists("Custom Field", CUSTOM_FIELD_NAME):
		return

	current = frappe.db.get_value("Custom Field", CUSTOM_FIELD_NAME, "fieldtype")
	if current == "Data":
		return

	frappe.db.set_value(
		"Custom Field",
		CUSTOM_FIELD_NAME,
		{
			"fieldtype": "Data",
			"precision": "",
			"options": None,
		},
		update_modified=False,
	)
	frappe.clear_cache(doctype="Sales Invoice Item")
	frappe.clear_cache(doctype="Custom Field")
