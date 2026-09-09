import frappe


def get_receivable_account(company):
    """
    Get receivable account for company
    Args:
        company: Company name
    """
    receivable_account = frappe.get_value(
        "Company", company, "default_receivable_account"
    )
    return receivable_account


def get_mode_of_payment_account(mode_of_payment: str, company=None):
    """
    Get mode of payment account for company
    Args:
        mode_of_payment: Mode of payment
        company: Company name
    """

    if not company:
        company = frappe.db.get_single_value("ArcPOS Settings", "company")

    # default cash and bank account
    cash_account = frappe.db.get_value("Company", company, "default_cash_account")
    bank_account = frappe.db.get_value("Company", company, "default_bank_account")

    # get mode of payment
    mode_of_payment_account = frappe.get_doc("Mode of Payment", mode_of_payment)
    if not mode_of_payment_account:
        frappe.throw(f"Mode of payment {mode_of_payment} not found")

    payment_account = None
    # get accounts for the company
    for account in mode_of_payment_account.accounts:
        if account.company == company:
            payment_account = account.default_account
            break

    # if no accounts found, use default cash or bank account
    if not payment_account and mode_of_payment_account.type == "Cash":
        payment_account = cash_account
    elif not payment_account and mode_of_payment_account.type == "Bank":
        payment_account = bank_account
    elif not payment_account:
        msg = f"Mode of payment {mode_of_payment} not found for company {company}"
        frappe.throw(msg)

    return payment_account


def get_payable_account(company):
    """
    Get payable account for company
    Args:
        company: Company name
    """
    payable_account = frappe.db.get_value("Company", company, "default_payable_account")
    return payable_account


def get_write_off_account(company):
    """
    Get write off account for company
    Args:
        company: Company name
    """
    write_off_account = frappe.db.get_value("Company", company, "write_off_account")
    return write_off_account


def fill_required_payment_entry_fields(payment_entry, invoice) -> None:
    """Fill custom fields another app has made mandatory on Payment Entry.

    excel_erpnext adds a required `excel_territory` with no default and nothing
    that populates it, so any Payment Entry built in code fails validation
    before it is ever saved. That takes down the gateway payment flow, where
    create_payment_entry runs inline from api.payments.receipt_payment -- after
    the customer has already been charged. The invoice already knows which
    territory the sale belongs to, so take it from there and fall back to the
    customer's.

    Written defensively on purpose: the field belongs to another app, so it may
    not be installed, and a site without it must not start failing here.
    """
    meta = frappe.get_meta("Payment Entry")
    if not meta.has_field("excel_territory") or payment_entry.get("excel_territory"):
        return

    territory = invoice.get("territory") or frappe.db.get_value(
        "Customer", invoice.get("customer"), "territory"
    )
    if territory:
        payment_entry.excel_territory = territory

