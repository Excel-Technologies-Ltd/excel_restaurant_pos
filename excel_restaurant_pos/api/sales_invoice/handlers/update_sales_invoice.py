import frappe
from frappe.utils import flt, add_days, getdate


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

        sales_invoice.append(
            "items",
            {
                "item_code": item_data.get("item_code"),
                "qty": flt(item_data.get("qty", 1)),
                "rate": flt(item_data.get("rate", 0)),
                "warehouse": item_data.get("warehouse"),
                "description": item_data.get("description"),
                "custom_parent_item": item_data.get("custom_parent_item"),
                "custom_serve_type": item_data.get("custom_serve_type"),
                "custom_order_item_status": item_data.get("custom_order_item_status"),
                "custom_if_not_available": item_data.get("custom_if_not_available"),
                "custom_special_note": item_data.get("custom_special_note"),
                "custom_is_print": item_data.get("custom_is_print"),
                "custom_new_ordered_item": item_data.get("custom_new_ordered_item"),
                "custom_guest_choice": item_data.get("custom_guest_choice"),
                "custom_is_offer_price": item_data.get("custom_is_offer_price"),
                "custom_choose_qty": item_data.get("custom_choose_qty"),
            },
        )
    sales_invoice.save(ignore_permissions=True)

    return sales_invoice
