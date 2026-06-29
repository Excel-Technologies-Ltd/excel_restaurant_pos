import frappe
from frappe.utils import cint, today, getdate

from excel_restaurant_pos.api.item_group import build_visible_item_filters

PAGINATION_KEYS = {"cmd", "limit", "limit_start", "limit_page_length"}


def _parse_pagination():
    limit_start = max(cint(frappe.form_dict.get("limit_start", 0)), 0)
    limit_page_length = cint(
        frappe.form_dict.get("limit_page_length") or frappe.form_dict.get("limit") or 10
    )
    limit_page_length = max(1, min(limit_page_length, 500))
    return limit_start, limit_page_length


def _build_base_filters():
    filters = frappe.form_dict.get("filters")
    default_filters = [["variant_of", "is", "not set"], ["disabled", "=", 0]]

    if not filters:
        return list(default_filters)

    filters = frappe.parse_json(filters)
    filters.extend(default_filters)
    return filters


def _build_list_query_params(filters, limit_start, limit_page_length):
    query_params = {
        key: value
        for key, value in frappe.form_dict.items()
        if key not in PAGINATION_KEYS and key != "filters"
    }
    query_params["filters"] = filters
    query_params["limit_start"] = limit_start
    query_params["limit_page_length"] = limit_page_length

    if not query_params.get("order_by"):
        query_params["order_by"] = "creation desc, item_code asc"

    return query_params


def _empty_item_list_response(limit_start, limit_page_length):
    return {
        "items": [],
        "total_count": 0,
        "has_more": False,
        "limit_start": limit_start,
        "limit_page_length": limit_page_length,
    }


def _attach_item_prices(item_list):
    item_codes = [item.item_code for item in item_list]
    if not item_codes:
        return item_list

    prices = frappe.get_all(
        "Item Price",
        filters={"item_code": ["in", item_codes], "selling": 1},
        fields=["item_code", "price_list", "price_list_rate", "valid_upto"],
    )

    today_date = getdate(today())
    price_map = {}
    for price in prices:
        if price.valid_upto and getdate(price.valid_upto) < today_date:
            continue

        item_code = price.item_code
        price_map.setdefault(item_code, []).append(price)

    for item in item_list:
        item["prices"] = price_map.get(item.item_code, [])

    return item_list


# get item list
@frappe.whitelist(allow_guest=True)
def get_item_list():
    """
    Get item list with visibility-aware pagination.

    filters:
        - variant_of: is not set (exclude item variants)
        - disabled: 0 (exclude disabled items)
    """
    limit_start, limit_page_length = _parse_pagination()
    base_filters = _build_base_filters()
    visibility_filters = build_visible_item_filters(base_filters)

    if visibility_filters is None:
        return _empty_item_list_response(limit_start, limit_page_length)

    total_count = frappe.db.count("Item", visibility_filters)
    query_params = _build_list_query_params(
        visibility_filters, limit_start, limit_page_length
    )
    item_list = frappe.get_all("Item", **query_params)
    item_list = _attach_item_prices(item_list)

    return {
        "items": item_list,
        "total_count": total_count,
        "has_more": limit_start + len(item_list) < total_count,
        "limit_start": limit_start,
        "limit_page_length": limit_page_length,
    }
