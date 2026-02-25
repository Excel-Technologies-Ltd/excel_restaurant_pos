"""
Create a payment entry.
"""

import frappe
from excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry import (
    create_payment_entry,
)


@frappe.whitelist()
def create_payment():
    """Create a payment entry."""

    # get required data from the form dictionary
    invoice_id = frappe.form_dict.get("invoice_id")
    payments = frappe.form_dict.get("payments")

    # get the invoice
    invoice = frappe.get_doc("Sales Invoice", invoice_id)
    if not invoice:
        frappe.throw("Invoice not found")

    if not payments:
        frappe.throw("Payments not found")

    # create the payment entry
    create_payment_entry(sales_invoice=invoice_id, payments=payments)

    return {"message": "Payment entry created successfully"}
