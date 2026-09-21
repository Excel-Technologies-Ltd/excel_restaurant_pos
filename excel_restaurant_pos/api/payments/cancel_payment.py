import frappe
from excel_restaurant_pos.shared.sales_invoice import delete_invoice_from_db
from .helper.check_receipt import check_receipt
from excel_restaurant_pos.shared.customer_access import access_level, require_login


@frappe.whitelist()
def cancel_payment():
    """
    Cancel a payment ticket.
    """

    # validate ticket
    require_login()
    ticket = frappe.form_dict.get("ticket")
    invoice_name = frappe.form_dict.get("order_no")
    if not ticket or not invoice_name:
        frappe.throw("Ticket and order number are required")

    # get ticket details
    invoice_no = frappe.db.get_value("Payment Ticket", {"ticket": ticket}, "invoice_no")
    if not invoice_no:
        frappe.throw("Invoice not found")
    # Cancelling deletes the draft order, so only its owner (or staff) may.
    access_level(invoice_no)

    # check if payment is alredy recipt or not
    receipt_status = check_receipt(ticket)
    r_result = receipt_status.get("receipt", {}).get("result")
    s_result = receipt_status.get("success", "false")
    order_number = receipt_status.get("request", {}).get("order_no")

    # if payment is already recipt, throw error
    if s_result == "true" and r_result == "a" and order_number == invoice_name:
        frappe.throw("Unable to cancel payment", frappe.ValidationError)

    # get invoice
    invoice = frappe.get_doc("Sales Invoice", invoice_no)
    if not invoice:
        frappe.throw("Invoice not found")

    # if invoice is in draft, delete the invoice
    if invoice.docstatus != 0:
        frappe.throw("Unable to cancel payment", frappe.ValidationError)

    # delete sales invoice from db
    delete_invoice_from_db(invoice_no)
    return {"success": True, "message": "Invoice deleted successfully"}
