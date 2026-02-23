import frappe
from frappe.utils import today, getdate


# get item details
@frappe.whitelist(allow_guest=True)
def get_item_details():
    """
    Get item details with variants
    """

    item_code = frappe.form_dict.get("item_code")
    if not item_code:
        frappe.throw("item_code is required")

    # Get item document and convert to dict
    item_details = frappe.get_doc("Item", item_code).as_dict()

    # Get variant items
    variant_fields = [
        "name",
        "item_name",
        "item_code",
        "item_group",
        "image",
        "description",
    ]
    variants_items = frappe.get_all(
        "Item", filters={"variant_of": item_code}, fields=variant_fields
    )

    # list of variant item codes
    regular_item_codes = [item.item_code for item in variants_items]

    # prepare attributes
    attributes_fields = [
        "attribute",
        "attribute_value",
        "custom_choice_type",
        "parent",
        "custom_max_choice_count",
    ]
    attributes = frappe.get_all(
        "Item Variant Attribute",
        filters={"parent": ["in", regular_item_codes]},
        fields=attributes_fields,
        order_by="creation",
    )

    attributes_map: dict[str, list[dict]] = {}
    for attribute in attributes:
        parent = attribute.parent
        # if attribute value is None, skip it
        if attribute.attribute_value is None:
            continue
        # if parent not in attributes_map, create a new list
        if parent not in attributes_map:
            attributes_map[parent] = []
        attributes_map[parent].append(attribute)

    # prepare addons items
    addons_items = item_details.get("custom_addons_items", [])
    addon_item_codes = [item.item_code for item in addons_items]

    # attach attributes to variants
    for variant in variants_items:
        variant.attributes = attributes_map.get(variant.item_code, [])

    # add docs item code
    regular_item_codes.append(item_code)

    # item prices
    regular_prices = frappe.get_all(
        "Item Price",
        filters={"item_code": ["in", regular_item_codes], "selling": 1},
        fields=["item_code", "price_list", "price_list_rate", "valid_upto"],
    )

    addon_prices = frappe.get_all(
        "Item Price",
        filters={"item_code": ["in", addon_item_codes], "price_list": "Add-on Price"},
        fields=["item_code", "price_list_rate"],
    )

    # Filter out expired prices based on valid_upto (only for regular items)
    today_date = getdate(today())

    # Filter regular prices
    valid_regular_prices = {}
    for price in regular_prices:
        if price.valid_upto:
            valid_upto_date = getdate(price.valid_upto)
            if valid_upto_date < today_date:
                continue  # Price is expired, skip it

        i_code = price.item_code
        if i_code not in valid_regular_prices:
            valid_regular_prices[i_code] = []
        valid_regular_prices[i_code].append(price)

    addon_price_map = {price.item_code: price.price_list_rate for price in addon_prices}

    # attach price to variants and addons
    for variant in variants_items:
        variant.price = valid_regular_prices.get(variant.item_code, [])

    # attach price to addons
    for addon in addons_items:
        addon.price = addon_price_map.get(addon.item_code, 0)

    # attach variants and addons to item details
    item_details["variants_items"] = variants_items
    item_details["prices"] = valid_regular_prices.get(item_code, [])

    return item_details
