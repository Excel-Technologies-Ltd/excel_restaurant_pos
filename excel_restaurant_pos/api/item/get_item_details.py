import frappe
from frappe.utils import today, getdate


VARIANT_FIELDS = [
    "name",
    "item_name",
    "item_code",
    "item_group",
    "image",
    "description",
]
VARIANT_ATTRIBUTE_FIELDS = [
    "attribute",
    "attribute_value",
    "custom_choice_type",
    "parent",
    "custom_max_choice_count",
]
REGULAR_PRICE_FIELDS = ["item_code", "price_list", "price_list_rate", "valid_upto"]
ADDON_PRICE_FIELDS = ["item_code", "price_list_rate"]


def _get_variant_items(item_code: str):
    return frappe.get_all(
        "Item", filters={"variant_of": item_code}, fields=VARIANT_FIELDS
    )


def _get_attributes_map(regular_item_codes: list[str]) -> dict[str, list[dict]]:
    if not regular_item_codes:
        return {}

    attributes = frappe.get_all(
        "Item Variant Attribute",
        filters={"parent": ["in", regular_item_codes]},
        fields=VARIANT_ATTRIBUTE_FIELDS,
        order_by="creation",
    )

    attribute_names = list(
        {attribute.attribute for attribute in attributes if attribute.get("attribute")}
    )
    item_attribute_value_map: dict[tuple[str, str], dict] = {}
    if attribute_names:
        item_attribute_values = frappe.get_all(
            "Item Attribute Value",
            filters={"parent": ["in", attribute_names]},
            fields=[
                "parent",
                "attribute_value",
                "abbr",
                "custom_child_item_name",
                "custom_child_max_choice",
            ],
        )
        item_attribute_value_map = {
            (row.parent, row.attribute_value): row for row in item_attribute_values
        }

    attributes_map: dict[str, list[dict]] = {}
    for attribute in attributes:
        if attribute.attribute_value is None:
            continue

        attribute.attribute_value_details = item_attribute_value_map.get(
            (attribute.attribute, attribute.attribute_value)
        )

        parent = attribute.parent
        if parent not in attributes_map:
            attributes_map[parent] = []
        attributes_map[parent].append(attribute)

    return attributes_map


def _get_regular_price_map(item_codes: list[str]) -> dict[str, list[dict]]:
    if not item_codes:
        return {}

    prices = frappe.get_all(
        "Item Price",
        filters={"item_code": ["in", item_codes], "selling": 1},
        fields=REGULAR_PRICE_FIELDS,
    )

    today_date = getdate(today())
    valid_price_map: dict[str, list[dict]] = {}
    for price in prices:
        if price.valid_upto and getdate(price.valid_upto) < today_date:
            continue

        valid_price_map.setdefault(price.item_code, []).append(price)

    return valid_price_map


def _get_addon_price_map(addon_item_codes: list[str]) -> dict[str, float]:
    if not addon_item_codes:
        return {}

    addon_prices = frappe.get_all(
        "Item Price",
        filters={"item_code": ["in", addon_item_codes], "price_list": "Add-on Price"},
        fields=ADDON_PRICE_FIELDS,
    )
    return {price.item_code: price.price_list_rate for price in addon_prices}


@frappe.whitelist(allow_guest=True)
def get_item_details():
    """Get item details with variants."""
    item_code = frappe.form_dict.get("item_code")
    if not item_code:
        frappe.throw("item_code is required")

    item_details = frappe.get_doc("Item", item_code).as_dict()
    variants_items = _get_variant_items(item_code)
    regular_item_codes = [item.item_code for item in variants_items]

    attributes_map = _get_attributes_map(regular_item_codes)
    addons_items = item_details.get("custom_addons_items", [])
    addon_item_codes = [item.item_code for item in addons_items]

    for variant in variants_items:
        variant.attributes = attributes_map.get(variant.item_code, [])

    regular_item_codes.append(item_code)
    valid_regular_prices = _get_regular_price_map(regular_item_codes)
    addon_price_map = _get_addon_price_map(addon_item_codes)

    for variant in variants_items:
        variant.price = valid_regular_prices.get(variant.item_code, [])

    for addon in addons_items:
        addon.price = addon_price_map.get(addon.item_code, 0)

    item_details["variants_items"] = variants_items
    item_details["prices"] = valid_regular_prices.get(item_code, [])
    return item_details
