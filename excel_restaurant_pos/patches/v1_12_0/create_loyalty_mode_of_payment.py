"""The tender points are paid with. Its company account is set from Loyalty Settings."""

import frappe

MODE = "Loyalty Points"


def execute():
	if not frappe.db.exists("Mode of Payment", MODE):
		frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": MODE, "type": "General", "enabled": 1}).insert(
			ignore_permissions=True
		)

	if not frappe.db.get_single_value("ArcPOS Loyalty Settings", "loyalty_mode_of_payment"):
		frappe.db.set_single_value("ArcPOS Loyalty Settings", "loyalty_mode_of_payment", MODE)
