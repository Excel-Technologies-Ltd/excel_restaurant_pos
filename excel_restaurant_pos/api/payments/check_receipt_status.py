import frappe
from .helper.check_receipt import check_receipt
from excel_restaurant_pos.shared.customer_access import access_level, require_login


@frappe.whitelist(allow_guest=True)
def check_receipt_status():
    """
    Check the receipt status of a payment ticket.
    """

    # validate ticket
    require_login()
    ticket = frappe.form_dict.get("ticket")
    if not ticket:
        frappe.throw("Ticket is required")

    # A Moneris receipt carries the order's payment details; owner or staff only.
    invoice_no = frappe.db.get_value("Payment Ticket", {"ticket": ticket}, "invoice_no")
    if not invoice_no:
        frappe.throw("Ticket not found")
    access_level(invoice_no)

    # check receipt status
    receipt_status = check_receipt(ticket)

    return receipt_status
