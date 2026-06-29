import frappe

from .visibility import filter_visible_item_groups


@frappe.whitelist(allow_guest=True)
def get_item_group_list():
    """
    Get distinct item group list that have items
    """

    combined_section = frappe.form_dict.get("custom_combined_section", None)
    i_filters = frappe.form_dict.get("item_filters", [])

    # Parse filters if it's a JSON string
    if isinstance(i_filters, str):
        i_filters = frappe.parse_json(i_filters) if i_filters else [["custom_is_website_item","=","1"]]
    
    # Ensure i_filters is a list
    if not isinstance(i_filters, list):
        i_filters = [["custom_is_website_item","=","1"]]

    # add the default filters
    item_filters = i_filters + [
        ["variant_of", "is", "not set"],
        ["disabled", "=", 0],
    ]

    if combined_section is not None:
        item_filters.append(
            ["custom_combined_section", "like", f"%{combined_section}%"]
        )
        frappe.form_dict.pop("custom_combined_section")

    # Get all item groups (may contain duplicates)
    item_groups = frappe.get_all("Item", filters=item_filters, pluck="item_group")

    # item groups
    if frappe.form_dict.get("cmd"):
        frappe.form_dict.pop("cmd")
    if frappe.form_dict.get("item_filters"):
        frappe.form_dict.pop("item_filters")

    # update filters
    filters = frappe.form_dict.get("filters")
    default_filters = [["name", "in", item_groups]]

    # Convert filters to list format if needed
    if not filters:
        filters = default_filters
    else:
        filters = frappe.parse_json(filters)
        filters.extend(default_filters)

    # Update form_dict with modified filters
    frappe.form_dict["filters"] = filters

    item_group_list = frappe.get_all("Item Group", **frappe.form_dict)

    return filter_visible_item_groups(item_group_list)
