import frappe
from frappe.utils import nowdate


def create_promotion_journal(invoice_name: str) -> str:
    """
    Create a promotion journal for the invoice if it doesn't exist
    """
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if not invoice:
        msg = f"Invoice not found for name: {invoice_name}"
        frappe.log_error("Invoice not found", msg)
        return

    # get first delivery quote
    custom_quotes = invoice.get("custom_quotes", []) or []
    if len(custom_quotes) == 0:
        msg = f"Delivery quote not found for invoice: {invoice_name}"
        frappe.log_error("Delivery quote not found", msg)
        return

    # get first delivery quote
    delivery_quote = custom_quotes[0]

    # actual delivery amount
    actual_delivery_amount = round(delivery_quote.get("fee", 0) / 100.0, 2)

    # charge amount
    taxes = invoice.get("taxes", [])
    delivery_charge = next(
        (t for t in taxes if t.get("custom_is_delivery_charge") == 1),
        None,
    )
    if not delivery_charge:
        msg = f"Delivery charge not found for invoice: {invoice_name}"
        frappe.log_error("Delivery charge not found", msg)
        return

    # actual charge amount
    charge_amount = delivery_charge.get("tax_amount", 0)

    # if not charge amout less than actual delivery amout return
    if charge_amount >= actual_delivery_amount:
        msg = f"Charge amount isn't less than actual delivery amount for invoice: {invoice_name}"
        frappe.log_error("Charge amount isn't less than actual delivery amount", msg)
        return

    # default dc account
    dc_account = frappe.db.get_single_value("ArcPOS Settings", "default_dc_account")
    if not dc_account:
        msg = f"Default DC account not found in ArcPOS Settings for invoice: {invoice_name}"
        frappe.log_error("Default DC account not found", msg)
        return

    # dc against account
    dc_against = frappe.db.get_single_value("ArcPOS Settings", "dc_against_account")
    if not dc_against:
        msg = f"DC against account not found in ArcPOS Settings for invoice: {invoice_name}"
        frappe.log_error("DC against account not found", msg)
        return

    # get default company
    company = frappe.db.get_single_value("ArcPOS Settings", "company")
    if not company:
        msg = f"Company not found in ArcPOS Settings for invoice: {invoice_name}"
        frappe.log_error("Company not found", msg)
        return

    # create journal entry
    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = company
    je.posting_date = nowdate()
    je.bill_no = invoice.name
    je.user_remark = "Promotional expense for delivery charge"

    # promotional expense amount
    promotional_expense_amount = round(actual_delivery_amount - charge_amount, 2)

    # Debit Entry
    je.append(
        "accounts",
        {
            "account": dc_against,
            "debit_in_account_currency": promotional_expense_amount,
        },
    )

    # Credit Entry
    je.append(
        "accounts",
        {
            "account": dc_account,
            "credit_in_account_currency": promotional_expense_amount,
        },
    )

    je.insert()
    je.submit()

    return je.name
