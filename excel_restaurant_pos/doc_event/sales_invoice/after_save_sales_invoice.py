"""Document event handlers for Sales Invoice after save."""

import frappe
from frappe.utils import flt

from excel_restaurant_pos.doc_event.shared import handle_table_occupy
from excel_restaurant_pos.shared.delivery_charge import get_delivery_charge


# enqueue occupy table job
def enqueue_occupy_table_job(doc, method: str):
    """
    Enqueue occupy table job
    """

    linked_table = doc.get("custom_linked_table", None)
    order_from = doc.get("custom_order_from", " ").lower()
    if linked_table and order_from == "table":
        args = {"table_name": linked_table, "sales_invoice": doc.name}
        frappe.enqueue(
            handle_table_occupy,
            queue="short",
            enqueue_after_commit=True,
            **args,
        )


# check delivery charge fraudulency
def check_delivery_and_charges_fraudulency(doc, method: str):
    """
    Check delivery charge fraudulency
    """

    s_type = doc.get("custom_service_type", "")
    allow_delivery_charge = frappe.db.get_single_value(
        "ArcPOS Settings", "allow_delivery_charge"
    )

    # if service type is not delivery, return
    if s_type != "Delivery":
        return

    # if delivery charge is not allowed, return
    if not allow_delivery_charge:
        return

    # if taxes is empty throw an error
    taxes = doc.get("taxes", [])
    if not taxes:
        msg = "Taxes and charges are required for delivery orders"
        frappe.throw(msg)

    # find the delivery entry in taxes
    delivery_entry = None
    for tax_data in taxes:
        if tax_data.get("custom_is_delivery_charge", 0):
            delivery_entry = tax_data
            break

    # if delivery entry is not found, throw an error
    if not delivery_entry:
        msg = "Delivery entry is required for delivery orders"
        frappe.throw(msg)

    # check if the delivery entry is fraudulent
    quotes = doc.get("custom_quotes", [])
    first_quote = quotes[0] if quotes else {}
    quote_amount = flt(first_quote.get("fee", 0)) / 100
    d_charge = get_delivery_charge(flt(doc.total), quote_amount)
    if d_charge != flt(delivery_entry.get("tax_amount", 0)):
        msg = f"Delivery charge mismatch: {d_charge} != {delivery_entry.get('tax_amount', 0)}"
        frappe.throw(msg)


# check tax fraudulency
def check_tax_fraudulency(doc, method: str):
    """
    Check tax fraudulency
    """
    s_type = doc.get("custom_service_type", "").lower()
    if s_type not in ["delivery", "pickup"]:
        return

    # fine the tax entry in taxes
    tax_entry = None
    for tax_data in doc.get("taxes", []):
        if tax_data.get("custom_is_tax", 0):
            tax_entry = tax_data
            break

    # if tax entry is not found, throw an error
    if not tax_entry:
        msg = "Tax entry is required for delivery and pickup orders"
        frappe.throw(msg)


# after save sales invoice
def after_save_sales_invoice(doc, method: str):
    """
    After save sales invoice
    """

    # enqueue occupy table job
    try:
        enqueue_occupy_table_job(doc, method)
    except Exception as e:
        frappe.log_error(
            "Sales Invoice After Save", f"Error enqueuing occupy table job: {e}"
        )

    # check delivery charge fraudulency
    try:
        check_delivery_and_charges_fraudulency(doc, method)
    except Exception as e:
        msg = f"Error checking delivery charge fraudulency: {e}"
        frappe.throw(msg)

    # check tax fraudulency
    try:
        check_tax_fraudulency(doc, method)
    except Exception as e:
        msg = f"Error checking tax fraudulency: {e}"
        frappe.throw(msg)
