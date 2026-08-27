"""Create Sales Invoice when a Table Order is completed."""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt


def create_sales_invoice_from_table_order(doc, method=None):
	"""On Table Order completion, create a submitted Sales Invoice with gift fields."""
	if doc.status != "Completed":
		return
	if doc.get("sales_invoice"):
		return

	if not doc.customer:
		frappe.throw("Customer is required")
	if not doc.item_list:
		frappe.throw("At least one item is required")

	restaurant_settings = frappe.get_doc("Restaurant Settings")
	tax_template_name = restaurant_settings.taxes_and_charges_template
	bom_settings = frappe.get_doc("Restaurant Production Config")

	if not tax_template_name:
		frappe.throw("Tax template not configured in Restaurant Settings")

	tax_template = frappe.get_doc("Sales Taxes and Charges Template", tax_template_name)
	tax_rate = 0
	charge_type = "On Net Total"
	account_head = ""
	if tax_template.taxes:
		tax_rate = flt(tax_template.taxes[0].get("rate", 0))
		charge_type = tax_template.taxes[0].get("charge_type", "On Net Total")
		account_head = tax_template.taxes[0].get("account_head", "")

	invoice_doc = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"customer": doc.customer,
			"docstatus": 0,
			"customer_name": doc.customer_name,
			"company": doc.company,
			"posting_date": frappe.utils.today(),
			"discount_amount": flt(doc.discount or 0),
			"apply_discount_on": "Net Total",
			"set_posting_time": 1,
			"update_stock": 1,
			"custom_gift_cards_for": (doc.get("custom_gift_cards_for") or "").strip(),
			"items": [],
			"taxes": [],
		}
	)

	for item in doc.item_list:
		if not item.item:
			continue
		row = {
			"item_code": item.item,
			"qty": flt(item.qty or 0),
			"rate": flt(item.rate or 0),
			"amount": flt(item.amount or 0),
			"warehouse": bom_settings.target_warehouse,
		}
		if cint(item.get("custom_is_gift_card_item")):
			row.update(
				{
					"custom_is_gift_card_item": 1,
					"custom_gift_card_type": (item.get("custom_gift_card_type") or "New").strip()
					or "New",
					"custom_gift_card_code": (item.get("custom_gift_card_code") or "").strip(),
					"custom_gift_amount": item.get("custom_gift_amount") or 0,
				}
			)
		invoice_doc.append("items", row)

	if tax_rate > 0 and account_head:
		invoice_doc.append(
			"taxes",
			{
				"charge_type": charge_type,
				"account_head": account_head,
				"rate": tax_rate,
				"description": "Sales Tax",
				"included_in_print_rate": 0,
			},
		)

	invoice_doc.insert(ignore_permissions=True)
	invoice_doc.submit()

	frappe.db.set_value("Table Order", doc.name, "sales_invoice", invoice_doc.name)
