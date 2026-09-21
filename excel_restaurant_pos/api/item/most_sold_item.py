import frappe


@frappe.whitelist()
def get_most_sold_item():
    """
    Get most sold items
    Returns complete Item documents with all fields
    """

    # pop cmd
    if frappe.form_dict.get("cmd"):
        frappe.form_dict.pop("cmd")

    # set default value
    frappe.form_dict.setdefault("limit", 20)
    frappe.form_dict.setdefault("limit_page_length", 20)

    # Use creation desc with item_code as secondary sort for consistent ordering
    order_by = frappe.form_dict.get("order_by")
    default_order_by = "custom_total_sold_qty desc"
    if not order_by:
        order_by = default_order_by
    else:
        order_by = frappe.parse_json(order_by)
        order_by.append(default_order_by)

    # update filters
    filters = frappe.form_dict.get("filters")
    default_filters = [["variant_of", "is", "not set"], ["disabled", "=", 0]]

    # Convert filters to list format if needed
    if not filters:
        filters = default_filters
    else:
        filters = frappe.parse_json(filters)
        filters.extend(default_filters)

    # Update form_dict with modified filters
    frappe.form_dict["filters"] = filters
    frappe.form_dict["order_by"] = order_by

    # get items
    items = frappe.get_all("Item", **frappe.form_dict)

    return items
