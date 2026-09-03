import frappe
from frappe.utils import add_days, getdate

from excel_restaurant_pos.shared.sales_invoice import build_invoice_item_row


def update_sales_invoice(invoice_name, items):
    sales_invoice = frappe.get_doc("Sales Invoice", invoice_name)

    # # Ensure posting_date is set and valid
    # if not sales_invoice.posting_date:
    #     sales_invoice.posting_date = frappe.utils.today()

    # # Normalize posting_date to ensure proper date comparison
    # posting_date = getdate(sales_invoice.posting_date)

    # # Set due_date to be at least equal to posting_date (1 day after)
    # # Use getdate to normalize the result and ensure proper date format
    # sales_invoice.due_date = getdate(add_days(posting_date, 1))

    # # Safety check: ensure due_date is never before posting_date
    # if getdate(sales_invoice.due_date) < posting_date:
    #     sales_invoice.due_date = posting_date

    for item_data in items:
        item_code = item_data.get("item_code", None)
        if not item_code:
            frappe.throw("Item code is required", frappe.ValidationError)

        if not frappe.db.exists("Item", item_code):
            frappe.throw(f"Item {item_code} not found", frappe.ValidationError)

        sales_invoice.append("items", build_invoice_item_row(item_data))

    sales_invoice.save(ignore_permissions=True)

    return sales_invoice
