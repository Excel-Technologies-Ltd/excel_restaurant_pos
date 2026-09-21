import frappe
from excel_restaurant_pos.shared.delivery_charge.validate_delivery_charge import get_delivery_charge


@frappe.whitelist()
def test():
    sales_invoice = frappe.get_doc("Sales Invoice", "ORD-26-01294")
    quotes = sales_invoice.get("custom_quotes") or []
    first_quote = quotes[0] if quotes else {}
    quote_amount = first_quote.get("fee", 0) / 100
    d_charge = get_delivery_charge(sales_invoice.total, quote_amount)
    return d_charge
    # if d_charge != tax_data.get("tax_amount", 0):
    #     frappe.throw(
    #         f"Delivery charge mismatch: {d_charge} != {tax_data.get('tax_amount', 0)}"
    #     )
    # return "Test From Sales Invoice Test Module"
