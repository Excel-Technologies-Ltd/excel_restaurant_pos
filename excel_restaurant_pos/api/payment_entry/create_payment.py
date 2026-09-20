"""
Create a payment entry.
"""

import frappe
from frappe import _

from excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry import (
    create_payment_entry,
)

# Recording a payment taken in person -- cash at the counter, a card on the
# terminal -- is a staff action. The storefront never calls this: order-web
# settles through Moneris (api.payments.get_ticket -> receipt_payment), which
# verifies the receipt before any Payment Entry exists. Only pos-web uses this,
# from the edit-order payment dialog.
#
# Before this list existed the endpoint was `@frappe.whitelist()` with no role
# check at all, so any authenticated user -- including an account self
# registered through the guest sign_up/verify_otp pair -- could mark any invoice
# paid for any amount without money moving.
PAYMENT_ROLES = (
    "System Manager",
    "Accounts Manager",
    "Accounts User",
    "ArcPOS Manager",
    "ArcPOS Register User",
    "Restaurant Manager",
    "Restaurant Cashier",
)

# site_config override, so a site with its own role names can add to the list
# without a deploy rather than being locked out of taking payments.
ROLES_CONFIG_KEY = "arcpos_payment_entry_roles"


def allowed_roles():
    configured = frappe.conf.get(ROLES_CONFIG_KEY)
    if not configured:
        return set(PAYMENT_ROLES)
    if isinstance(configured, str):
        configured = [configured]

    return set(PAYMENT_ROLES) | {str(role).strip() for role in configured if str(role).strip()}


def guard_payment_permission():
    """Refuse anyone who is not staff, and leave a trail when we do."""
    user = frappe.session.user if frappe.session else "Guest"
    if user == "Administrator":
        return

    if not (set(frappe.get_roles(user)) & allowed_roles()):
        frappe.log_error(
            title="Payment entry refused: not a payment role",
            message=f"user={user} invoice={frappe.form_dict.get('invoice_id')!r}",
        )
        frappe.throw(
            _("You are not permitted to record payments."), frappe.PermissionError
        )


@frappe.whitelist(methods=["POST"])
def create_payment():
    """Create a payment entry."""
    guard_payment_permission()

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
