import frappe

from .helper.check_receipt import check_receipt
from excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry import (
    create_payment_entry,
)


@frappe.whitelist(allow_guest=True)
def receipt_payment():
    """
    Receipt a payment ticket.
    """

    # validate ticket
    ticket = frappe.form_dict.get("ticket")
    invoice_name = frappe.form_dict.get("order_no")
    if not ticket or not invoice_name:
        frappe.throw("Ticket and order number are required")

    # get ticket details
    invoice_no = frappe.db.get_value("Payment Ticket", {"ticket": ticket}, "invoice_no")
    if not invoice_no:
        frappe.throw("Ticket not found")

    # check receipt status info
    receipt_status = check_receipt(ticket)

    # define required values for validation
    receipt_result = receipt_status.get("receipt", {}).get("result", "")
    success_result = receipt_status.get("success", "false")

    # check payment is successful and the receipt is approved
    is_development = frappe.conf.get("environment", None) == "development"
    if not is_development:
        if success_result != "true" or receipt_result != "a":
            frappe.throw("Invalid or expired payment ticket", frappe.ValidationError)

    # # validate order number
    order_number = receipt_status.get("request", {}).get("order_no")
    if order_number != invoice_name:
        frappe.throw("Order number mismatch", frappe.ValidationError)

    # get invoice
    invoice = frappe.get_doc("Sales Invoice", invoice_no)
    if not invoice:
        frappe.throw("Invoice not found")

    # check receipt payment
    payments = frappe.form_dict.get("payments", None)
    if not payments:
        frappe.throw("Payments are required")

    # submit sales invoice with payment data
    invoice.docstatus = 1
    invoice.save(ignore_permissions=True)

    # enqueue payment entry creation
    args = {"sales_invoice": invoice.name, "payments": payments}
    create_payment_entry(**args)
    # frappe.enqueue(create_payment_entry, queue="short", **args)

    # return True
    return {"success": True}
