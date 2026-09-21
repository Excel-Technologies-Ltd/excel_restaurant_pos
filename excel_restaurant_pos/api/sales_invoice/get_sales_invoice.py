import frappe

from excel_restaurant_pos.shared.customer_access import access_level, as_seen_by

@frappe.whitelist(methods=["GET"])
def get_sales_invoice():
    """
    Get a sales invoice by name
    Args:
        invoice_name: The name of the sales invoice to get
    Returns:
        The sales invoice as a dictionary
    """
    invoice_name = frappe.form_dict.get("invoice_name", None)
    if not invoice_name:
        frappe.throw("Invoice name is required")


    # Before any lookup, so a guest cannot even learn whether an order number
    # exists. This used to return any order to anyone, by sequential name.
    level = access_level(invoice_name, allow_table=True)

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    return as_seen_by(invoice, level)