import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.utils import cint

from .visibility import get_visible_item_group_names

ITEM_DOCTYPE = "Item"
ITEM_GROUP_DOCTYPE = "Item Group"

# Gift card flags: one on the Item, one on the Item Group.
GIFT_CARD_ITEM_FIELD = "custom_is_gift_card_item"
GIFT_CARD_GROUP_FIELD = "custom_is_gift_card"

# Standard columns every DocType has, on top of its DocFields.
STANDARD_FIELDS = ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx")


def _parse_json_arg(value):
    """Parse a request argument that may arrive as a JSON string."""
    if isinstance(value, str):
        value = value.strip()
        return frappe.parse_json(value) if value else None
    return value


def _permitted_fieldnames():
    """Item Group columns a caller may read or filter on.

    `frappe.get_all` runs with `ignore_permissions=True`, which also switches off
    field level permissions, so the allowlist has to live here.
    """
    meta = frappe.get_meta(ITEM_GROUP_DOCTYPE)
    return set(STANDARD_FIELDS) | {
        df.fieldname for df in meta.fields if df.fieldtype not in no_value_fields
    }


def _validate_fieldname(fieldname, permitted):
    if fieldname not in permitted:
        frappe.throw(
            _("{0} is not a valid Item Group field").format(fieldname),
            frappe.ValidationError,
        )


def _requested_fields(permitted):
    fields = _parse_json_arg(frappe.form_dict.get("fields"))
    if not fields:
        return ["name"]

    if isinstance(fields, str):
        fields = [fields]

    # "*" stays supported, but expands to the known columns rather than reaching
    # the query builder, where it would also pull anything added later.
    if any(field == "*" for field in fields):
        return sorted(permitted)

    for field in fields:
        _validate_fieldname(field, permitted)

    return list(fields)


def _requested_order_by(permitted):
    """Rebuild the sort clause from validated fieldnames.

    Comma separated sorts are supported, so `custom_priority desc, name asc`
    keeps working.
    """
    order_by = (frappe.form_dict.get("order_by") or "").strip()
    if not order_by:
        return None

    clauses = []
    for clause in order_by.replace("`", "").split(","):
        parts = clause.split()
        if not parts or len(parts) > 2:
            frappe.throw(_("Invalid order by: {0}").format(order_by), frappe.ValidationError)

        fieldname = parts[0]
        direction = parts[1].lower() if len(parts) == 2 else "asc"
        _validate_fieldname(fieldname, permitted)
        if direction not in ("asc", "desc"):
            frappe.throw(
                _("Invalid sort direction: {0}").format(direction), frappe.ValidationError
            )

        clauses.append(f"`tab{ITEM_GROUP_DOCTYPE}`.`{fieldname}` {direction}")

    return ", ".join(clauses)


def _requested_filters(permitted):
    """Caller supplied Item Group filters, as a list of [field, operator, value]."""
    filters = _parse_json_arg(frappe.form_dict.get("filters"))
    if not filters:
        return []

    if isinstance(filters, dict):
        filters = [[fieldname, "=", value] for fieldname, value in filters.items()]

    normalized = []
    for filter_row in filters:
        if isinstance(filter_row, dict):
            normalized.extend([fieldname, "=", value] for fieldname, value in filter_row.items())
            continue
        if not isinstance(filter_row, (list, tuple)) or len(filter_row) != 3:
            frappe.throw(
                _("Each filter must be [field, operator, value]"), frappe.ValidationError
            )
        normalized.append(list(filter_row))

    for filter_row in normalized:
        _validate_fieldname(filter_row[0], permitted)

    return normalized


def _page_args():
    form = frappe.form_dict
    limit_start = cint(form.get("limit_start") or form.get("start") or 0)
    limit_page_length = form.get("limit_page_length") or form.get("limit") or form.get("page_length")
    # No limit by default, which is what the unfiltered query returned before.
    return limit_start, cint(limit_page_length) if limit_page_length else None


def _wants_gift_cards():
    """Whether gift card items and groups should be included in the result.

    Off by default: the POS asks for the gift card catalogue explicitly.
    """
    form = frappe.form_dict
    return cint(form.get(GIFT_CARD_GROUP_FIELD) or form.get("include_gift_cards") or 0)


def _build_item_filters(include_gift_cards):
    """Filters for the Item query that decides which groups have sellable items."""
    caller_filters = frappe.form_dict.get("item_filters")

    if isinstance(caller_filters, str):
        caller_filters = frappe.parse_json(caller_filters) if caller_filters.strip() else None
    if caller_filters is not None and not isinstance(caller_filters, list):
        caller_filters = None

    # Historical quirk, kept deliberately: the website default only applies when
    # `item_filters` is sent but unusable, never when it is omitted.
    if caller_filters is None and "item_filters" in frappe.form_dict:
        caller_filters = [["custom_is_website_item", "=", "1"]]

    item_filters = list(caller_filters or []) + [
        ["variant_of", "is", "not set"],
        ["disabled", "=", 0],
    ]

    if not include_gift_cards:
        # `= 0` rather than `!= 1` so rows that never had the flag set are kept:
        # db_query wraps a falsy value in ifnull(column, 0).
        item_filters.append([GIFT_CARD_ITEM_FIELD, "=", 0])

    combined_section = frappe.form_dict.get("custom_combined_section")
    if combined_section:
        item_filters.append(["custom_combined_section", "like", f"%{combined_section}%"])

    return item_filters


def _gift_card_group_names():
    return frappe.get_all(
        ITEM_GROUP_DOCTYPE, filters={GIFT_CARD_GROUP_FIELD: 1}, pluck="name"
    )


def _candidate_group_names(include_gift_cards):
    """Item groups that hold at least one sellable item and are visible now."""
    group_names = set(
        frappe.get_all(
            ITEM_DOCTYPE,
            filters=_build_item_filters(include_gift_cards),
            pluck="item_group",
            distinct=True,
            # No ORDER BY: sorting by `modified` alongside a DISTINCT on
            # `item_group` is what MySQL rejects under ONLY_FULL_GROUP_BY.
            order_by=None,
        )
    )
    group_names.discard(None)
    if not group_names:
        return []

    if not include_gift_cards:
        group_names -= set(_gift_card_group_names())
        if not group_names:
            return []

    # Visibility is resolved before the list query rather than after it, so a
    # paged request no longer returns short pages.
    return get_visible_item_group_names(sorted(group_names))


@frappe.whitelist(allow_guest=True)
def get_item_group_list():
    """Item groups that currently have sellable items.

    Request arguments (all optional):
        item_filters              extra filters for the underlying Item query
        custom_combined_section   match items by combined section
        custom_is_gift_card       1 to include gift card items and groups
        filters, fields, order_by, limit_start, limit_page_length

    Anything else in the request is ignored.
    """
    include_gift_cards = _wants_gift_cards()

    group_names = _candidate_group_names(include_gift_cards)
    if not group_names:
        return []

    permitted = _permitted_fieldnames()
    limit_start, limit_page_length = _page_args()

    query_args = {
        "filters": _requested_filters(permitted) + [["name", "in", group_names]],
        "fields": _requested_fields(permitted),
        "limit_start": limit_start,
        "limit_page_length": limit_page_length,
    }

    # Left out unless asked for, so the DocType default (`modified desc`) still
    # applies -- passing order_by=None would drop the ORDER BY altogether.
    order_by = _requested_order_by(permitted)
    if order_by:
        query_args["order_by"] = order_by

    return frappe.get_all(ITEM_GROUP_DOCTYPE, **query_args)
