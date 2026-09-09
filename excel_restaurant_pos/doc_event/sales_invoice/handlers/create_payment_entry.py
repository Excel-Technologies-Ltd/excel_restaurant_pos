import frappe
from frappe.utils import nowdate
from excel_restaurant_pos.shared.sales_invoice import (
    fill_required_payment_entry_fields,
    get_receivable_account,
    get_mode_of_payment_account,
)


def create_payment_entry(sales_invoice, payments=None):
    frappe.set_user("Administrator")

    doc = frappe.get_doc("Sales Invoice", sales_invoice)

    receivable_account = get_receivable_account(doc.company)
    if not receivable_account:
        frappe.throw(f"Receivable account not found for company {doc.company}")

    if not payments:
        payments = doc.payments

    for payment in payments:
        mode_of_payment = (
            payment.get("mode_of_payment")
            if isinstance(payment, dict)
            else payment.mode_of_payment
        )
        amount = payment.get("amount") if isinstance(payment, dict) else payment.amount

        if not mode_of_payment or not amount:
            continue

        account = get_mode_of_payment_account(mode_of_payment, doc.company)
        if not account:
            continue

        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Receive"
        payment_entry.posting_date = nowdate()
        payment_entry.mode_of_payment = mode_of_payment
        payment_entry.party_type = "Customer"
        payment_entry.party = doc.customer
        payment_entry.company = doc.company

        payment_entry.paid_from = receivable_account
        payment_entry.paid_to = account
        payment_entry.paid_amount = amount
        payment_entry.received_amount = amount

        payment_entry.append(
            "references",
            {
                "reference_doctype": "Sales Invoice",
                "reference_name": doc.name,
                "allocated_amount": amount,
            },
        )

        # Without this the insert dies on excel_erpnext's mandatory
        # excel_territory, which takes down every gateway payment: this runs
        # inline from api.payments.receipt_payment, after the customer has
        # already been charged.
        fill_required_payment_entry_fields(payment_entry, doc)

        payment_entry.insert(ignore_permissions=True)
        payment_entry.submit()
