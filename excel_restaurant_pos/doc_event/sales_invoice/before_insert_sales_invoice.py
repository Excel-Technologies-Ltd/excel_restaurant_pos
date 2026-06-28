"""Document event handler for Sales Invoice validation."""

import frappe


def before_insert_sales_invoice(doc, method: str):
    """
    Validate Sales Invoice
    Args:
        doc: The Sales Invoice document.
        method: The method being called.
    """
    # Bypass modified check for POS invoices created+submitted in one flow
    # (Frappe's internal logic can update the doc between insert and submit, causing conflict)
    # Also bypass for any POS invoice (is_pos=1) to prevent version conflicts during creation
    if doc.get("is_pos") == 1:
        doc.flags.ignore_version = True

    order_from = None
    status = None
    table_name = None

    if doc.custom_order_from:
        order_from = doc.custom_order_from.lower()

    if order_from and "table" in order_from and doc.custom_linked_table:
        table_name = doc.custom_linked_table
        status = frappe.db.get_value("Restaurant Table", table_name, "status")

    if status and status != "Available":
        frappe.throw(f"{table_name} is already occupied or unavailable")
