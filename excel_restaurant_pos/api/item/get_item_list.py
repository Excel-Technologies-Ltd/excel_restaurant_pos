import json

import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.utils import cint, today, getdate

from excel_restaurant_pos.api.item.search import find_ranked_names
from excel_restaurant_pos.api.item_group import build_visible_item_filters

ITEM_DOCTYPE = "Item"
GIFT_CARD_ITEM_FIELD = "custom_is_gift_card_item"

# Keys this endpoint consumes itself. Everything else in form_dict is still
# splatted into frappe.get_all, so a key it reads must never reach the query
# builder as a keyword argument.
SEARCH_KEYS = ("search", "q")

PAGINATION_KEYS = {
    "cmd",
    "limit",
    "limit_start",
    "limit_page_length",
    GIFT_CARD_ITEM_FIELD,
    *SEARCH_KEYS,
}


def _item_fieldnames():
    meta = frappe.get_meta(ITEM_DOCTYPE)
    return {df.fieldname for df in meta.fields if df.fieldtype not in no_value_fields}


def _gift_card_filter():
    """`custom_is_gift_card_item` as a top level request parameter.

    Absent means no filter at all, so the default result is unchanged. `1`
    returns only gift card items, `0` only the rest. The field also works inside
    `filters`; this shorthand saves building a filter array for the common case.
    """
    raw = frappe.form_dict.get(GIFT_CARD_ITEM_FIELD)
    if raw in (None, ""):
        return None

    if GIFT_CARD_ITEM_FIELD not in _item_fieldnames():
        frappe.throw(
            _("{0} is not a field on {1} on this site").format(
                GIFT_CARD_ITEM_FIELD, _(ITEM_DOCTYPE)
            ),
            frappe.ValidationError,
        )

    return [GIFT_CARD_ITEM_FIELD, "=", cint(raw)]


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
        filters = []
    else:
        filters = frappe.parse_json(filters)
        # Dict shaped filters are what the Desk sends; .extend() would fail.
        if isinstance(filters, dict):
            filters = [[fieldname, "=", value] for fieldname, value in filters.items()]
        else:
            filters = list(filters)

    filters.extend(default_filters)

    gift_card_filter = _gift_card_filter()
    if gift_card_filter:
        filters.append(gift_card_filter)

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


def _empty_item_list_response(limit_start, limit_page_length, total_count=0):
    return {
        "items": [],
        "total_count": total_count,
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


def _search_term():
    for key in SEARCH_KEYS:
        value = frappe.form_dict.get(key)
        if value and str(value).strip():
            return str(value)

    return None


def _parse_fields(fields):
    """`fields` the way DatabaseQuery.parse_args reads it, before it gets there."""
    if not isinstance(fields, str):
        return list(fields)
    if fields == "*":
        return ["*"]
    try:
        return list(json.loads(fields))
    except ValueError:
        return [field.strip() for field in fields.split(",")]


def _ensure_name_field(query_params):
    """Guarantee `name` comes back, since the ranked order is keyed on it.

    get_all only returns the fields it was asked for, and a caller is free to
    ask for a list without `name`. Returns whether the caller wanted it, so a
    response can be handed back the same shape a search-free request would give.
    """
    fields = query_params.get("fields")
    if not fields:
        # get_all defaults to ["name"].
        return True

    fields = _parse_fields(fields)
    if "*" in fields or "name" in fields:
        query_params["fields"] = fields
        return True

    query_params["fields"] = fields + ["name"]
    return False


def _fetch_ranked_page(visibility_filters, ranked_names, limit_start, limit_page_length):
    """Fetch one page of an already ranked name list, still ranked.

    The names are paginated before anything is fetched, so the number of rows
    built into documents is the page size no matter how many items matched.
    """
    page_names = ranked_names[limit_start : limit_start + limit_page_length]
    if not page_names:
        return []

    query_params = _build_list_query_params(
        visibility_filters + [["name", "in", page_names]], 0, len(page_names)
    )
    # Relevance is the order when searching, so whatever order the rows come
    # back in is undone below.
    query_params["order_by"] = "item_name asc"
    wanted_name = _ensure_name_field(query_params)

    item_list = frappe.get_all("Item", **query_params)
    by_name = {item.name: item for item in item_list}

    ordered = [by_name[name] for name in page_names if name in by_name]
    if not wanted_name:
        for item in ordered:
            item.pop("name", None)

    return ordered


def _search_item_list(search_term, visibility_filters, limit_start, limit_page_length):
    ranked_names = find_ranked_names(search_term, visibility_filters)
    if ranked_names is None:
        # Punctuation only, so there is nothing to search for. Treated as no
        # search at all rather than as a search that matched nothing.
        return None

    item_list = _fetch_ranked_page(
        visibility_filters, ranked_names, limit_start, limit_page_length
    )
    total_count = len(ranked_names)

    if not item_list:
        return _empty_item_list_response(limit_start, limit_page_length, total_count)

    return {
        "items": _attach_item_prices(item_list),
        "total_count": total_count,
        "has_more": limit_start + len(item_list) < total_count,
        "limit_start": limit_start,
        "limit_page_length": limit_page_length,
    }


# get item list
@frappe.whitelist(allow_guest=True)
def get_item_list():
    """
    Get item list with visibility-aware pagination.

    filters:
        - variant_of: is not set (exclude item variants)
        - disabled: 0 (exclude disabled items)

    `search` (or `q`) turns on typo tolerant ranked search over the same rows.
    It is optional and changes nothing when absent; every other parameter --
    filters, pagination, the gift card shorthand -- keeps working alongside it.
    Results come back most relevant first, which replaces the default ordering
    for that request.
    """
    limit_start, limit_page_length = _parse_pagination()
    base_filters = _build_base_filters()
    visibility_filters = build_visible_item_filters(base_filters)

    if visibility_filters is None:
        return _empty_item_list_response(limit_start, limit_page_length)

    search_term = _search_term()
    if search_term:
        response = _search_item_list(
            search_term, visibility_filters, limit_start, limit_page_length
        )
        if response is not None:
            return response

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
