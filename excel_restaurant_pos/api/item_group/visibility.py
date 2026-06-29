import datetime

import frappe
from frappe import _
from frappe.utils import get_time, getdate, nowdate, nowtime

VISIBILITY_CACHE_PREFIX = "arcpos:visible_item_groups"
VISIBILITY_CACHE_TTL = 60


def _time_to_seconds(value):
    if not value:
        return None
    if isinstance(value, datetime.timedelta):
        return int(value.total_seconds())
    if isinstance(value, datetime.time):
        return value.hour * 3600 + value.minute * 60 + value.second

    time_obj = get_time(value)
    return time_obj.hour * 3600 + time_obj.minute * 60 + time_obj.second


def _is_within_date_range(starts_on, till_date, current_date):
    if not starts_on and not till_date:
        return True
    if starts_on and current_date < getdate(starts_on):
        return False
    if till_date and current_date > getdate(till_date):
        return False
    return True


def _is_within_time_slots(time_slots, current_time):
    if not time_slots:
        return True

    current_seconds = _time_to_seconds(current_time)
    for slot in time_slots:
        start = _time_to_seconds(slot.get("start_time"))
        end = _time_to_seconds(slot.get("end_time"))
        if start is None or end is None:
            continue
        if start <= end:
            if start <= current_seconds <= end:
                return True
        elif current_seconds >= start or current_seconds <= end:
            return True
    return False


def _fetch_visibility_data(item_group_names):
    visibility_rows = frappe.get_all(
        "Item Group",
        filters={"name": ["in", item_group_names]},
        fields=["name", "custom_visibility_starts_on", "custom_visibility_till_date"],
    )
    visibility_by_name = {row["name"]: row for row in visibility_rows}

    time_slot_rows = frappe.get_all(
        "Visibility Time Slot",
        filters={
            "parent": ["in", item_group_names],
            "parenttype": "Item Group",
            "parentfield": "custom_visibility_time_bound",
        },
        fields=["parent", "start_time", "end_time"],
    )
    time_slots_by_parent = {}
    for slot in time_slot_rows:
        time_slots_by_parent.setdefault(slot["parent"], []).append(slot)

    return visibility_by_name, time_slots_by_parent


def _is_item_group_visible(
    item_group_name,
    visibility_by_name,
    time_slots_by_parent,
    current_date,
    current_time,
):
    visibility = visibility_by_name.get(item_group_name, {})
    starts_on = visibility.get("custom_visibility_starts_on")
    till_date = visibility.get("custom_visibility_till_date")
    time_slots = time_slots_by_parent.get(item_group_name, [])

    if not starts_on and not till_date and not time_slots:
        return True

    return _is_within_date_range(starts_on, till_date, current_date) and _is_within_time_slots(
        time_slots, current_time
    )


def get_item_group_visibility_map(item_group_names, current_date=None, current_time=None):
    """Return a map of item group name to current visibility status."""
    item_group_names = list({name for name in item_group_names if name})
    if not item_group_names:
        return {}

    current_date = getdate(current_date or nowdate())
    current_time = current_time or nowtime()
    visibility_by_name, time_slots_by_parent = _fetch_visibility_data(item_group_names)

    return {
        name: _is_item_group_visible(
            name, visibility_by_name, time_slots_by_parent, current_date, current_time
        )
        for name in item_group_names
    }


def get_visible_item_group_names(item_group_names, current_date=None, current_time=None):
    """Return item group names that are currently visible."""
    visibility_map = get_item_group_visibility_map(
        item_group_names, current_date=current_date, current_time=current_time
    )
    return [name for name in item_group_names if visibility_map.get(name, True)]


def _visibility_cache_key(current_date=None, current_time=None):
    current_date = getdate(current_date or nowdate())
    current_time = get_time(current_time or nowtime())
    return (
        f"{VISIBILITY_CACHE_PREFIX}:{current_date}:"
        f"{current_time.hour:02d}:{current_time.minute:02d}"
    )


def get_cached_visible_item_group_names(current_date=None, current_time=None):
    """Return currently visible item groups, cached by minute."""
    cache_key = _visibility_cache_key(current_date, current_time)
    cached = frappe.cache().get_value(cache_key)
    if cached is not None:
        return cached

    all_groups = frappe.get_all("Item Group", pluck="name")
    visible_groups = get_visible_item_group_names(
        all_groups, current_date=current_date, current_time=current_time
    )
    frappe.cache().set_value(cache_key, visible_groups, expires_in_sec=VISIBILITY_CACHE_TTL)
    return visible_groups


def clear_visible_item_group_cache():
    """Clear cached visible item group snapshots."""
    frappe.cache().delete_keys(f"{VISIBILITY_CACHE_PREFIX}:*")


def _extract_item_group_filter_values(filters):
    values = set()
    has_item_group_filter = False

    for filter_row in filters:
        if not isinstance(filter_row, (list, tuple)) or len(filter_row) < 3:
            continue

        field, operator, value = filter_row[0], filter_row[1], filter_row[2]
        if field != "item_group":
            continue

        has_item_group_filter = True
        if operator == "=":
            values.add(value)
        elif operator == "in":
            values.update(value if isinstance(value, (list, tuple, set)) else [value])

    return values if has_item_group_filter else None


def _without_item_group_filters(filters):
    return [
        filter_row
        for filter_row in filters
        if not (
            isinstance(filter_row, (list, tuple))
            and len(filter_row) >= 1
            and filter_row[0] == "item_group"
        )
    ]


def build_visible_item_filters(filters, current_date=None, current_time=None):
    """
    Extend item filters to only include items in currently visible item groups.

    Returns updated filters, or None when no visible items match.
    """
    visible_groups = set(
        get_cached_visible_item_group_names(current_date=current_date, current_time=current_time)
    )
    if not visible_groups:
        return None

    restricted_groups = _extract_item_group_filter_values(filters)
    if restricted_groups is not None:
        visible_groups &= restricted_groups

    if not visible_groups:
        return None

    visibility_filters = _without_item_group_filters(filters)
    visible_group_list = list(visible_groups)

    if len(visible_group_list) == 1:
        visibility_filters.append(["item_group", "=", visible_group_list[0]])
    else:
        visibility_filters.append(["item_group", "in", visible_group_list])

    return visibility_filters


def filter_visible_item_groups(item_group_list, current_date=None, current_time=None):
    """Filter item groups by configured visibility date range and time slots."""
    if not item_group_list:
        return item_group_list

    item_group_names = [row["name"] for row in item_group_list if row.get("name")]
    visibility_map = get_item_group_visibility_map(
        item_group_names, current_date=current_date, current_time=current_time
    )

    visible_item_groups = []
    for item_group in item_group_list:
        name = item_group.get("name")
        if not name or visibility_map.get(name, True):
            visible_item_groups.append(item_group)

    return visible_item_groups


def filter_visible_items(item_list, current_date=None, current_time=None):
    """Filter items by their item group's visibility date range and time slots."""
    if not item_list:
        return item_list

    item_group_names = []
    item_codes_missing_group = []

    for item in item_list:
        item_group = item.get("item_group")
        if item_group:
            item_group_names.append(item_group)
            continue

        item_code = item.get("item_code") or item.get("name")
        if item_code:
            item_codes_missing_group.append(item_code)

    if item_codes_missing_group:
        item_rows = frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes_missing_group]},
            fields=["name", "item_group"],
        )
        item_group_by_code = {row["name"]: row["item_group"] for row in item_rows}
        for item in item_list:
            if item.get("item_group"):
                continue
            item_code = item.get("item_code") or item.get("name")
            item_group = item_group_by_code.get(item_code)
            if item_group:
                item["item_group"] = item_group
                item_group_names.append(item_group)

    visibility_map = get_item_group_visibility_map(
        item_group_names, current_date=current_date, current_time=current_time
    )

    return [
        item
        for item in item_list
        if not item.get("item_group") or visibility_map.get(item.get("item_group"), True)
    ]


def _normalize_invoice_items(items):
    normalized_items = []
    item_codes_missing_group = []

    for item in items:
        item_code = item.get("item_code")
        normalized_items.append(
            {
                "item_code": item_code,
                "item_name": item.get("item_name") or item_code,
                "item_group": item.get("item_group"),
            }
        )
        if item_code and not item.get("item_group"):
            item_codes_missing_group.append(item_code)

    if item_codes_missing_group:
        item_group_rows = frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes_missing_group]},
            fields=["name", "item_group"],
        )
        item_group_map = {row["name"]: row["item_group"] for row in item_group_rows}
        for row in normalized_items:
            if not row["item_group"] and row["item_code"] in item_group_map:
                row["item_group"] = item_group_map[row["item_code"]]

    return normalized_items


def get_unavailable_invoice_items(items, current_date=None, current_time=None):
    """Return invoice items whose item groups are not currently visible."""
    normalized_items = _normalize_invoice_items(items)
    item_group_names = [row["item_group"] for row in normalized_items if row.get("item_group")]
    visibility_map = get_item_group_visibility_map(
        item_group_names, current_date=current_date, current_time=current_time
    )

    unavailable_items = []
    seen_item_codes = set()
    for row in normalized_items:
        item_group = row.get("item_group")
        item_code = row.get("item_code")
        if not item_group or not item_code or item_code in seen_item_codes:
            continue
        if visibility_map.get(item_group, True):
            continue

        seen_item_codes.add(item_code)
        unavailable_items.append(row)

    return unavailable_items


def validate_item_group_visibility(items, current_date=None, current_time=None):
    """Raise a validation error when any item's group is outside its visibility window."""
    unavailable_items = get_unavailable_invoice_items(
        items, current_date=current_date, current_time=current_time
    )
    if not unavailable_items:
        return

    item_labels = [
        _("{0} ({1})").format(item["item_name"], item["item_group"])
        for item in unavailable_items
    ]
    frappe.throw(
        _("The following items are not currently available for sale: {0}").format(
            ", ".join(item_labels)
        ),
        title=_("Items Not Available"),
        exc=frappe.ValidationError,
    )
