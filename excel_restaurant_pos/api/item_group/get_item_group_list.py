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
    """Parse a request argument that may arrive as a JSON string.

    A string that is not JSON is handed back as-is rather than raising, so a
    bare `fields=*` or `fields=item_group_name` behaves like the one element
    list it means.
    """
    if not isinstance(value, str):
        return value

    value = value.strip()
    if not value:
        return None

    try:
        return frappe.parse_json(value)
    except ValueError:
        return value


def _permitted_fieldnames(doctype=ITEM_GROUP_DOCTYPE):
    """Columns of `doctype` a caller may read or filter on.

    `frappe.get_all` runs with `ignore_permissions=True`, which also switches off
    field level permissions, so the allowlist has to live here.
    """
    meta = frappe.get_meta(doctype)
    return set(STANDARD_FIELDS) | {
        df.fieldname for df in meta.fields if df.fieldtype not in no_value_fields
    }


def _field_exists(doctype, fieldname):
    """Whether a field is actually on the DocType on this site.

    Fixtures can lag behind the code, and a filter on a column that does not
    exist yet fails as a raw SQL error rather than anything a caller can act on.
    """
    return fieldname in _permitted_fieldnames(doctype)


def _validate_fieldname(fieldname, permitted, doctype=ITEM_GROUP_DOCTYPE):
    if fieldname in permitted:
        return

    # The gift card flag is named differently on each DocType, so sending it
    # against the wrong one is a likelier mistake than a typo.
    if fieldname in (GIFT_CARD_GROUP_FIELD, GIFT_CARD_ITEM_FIELD):
        frappe.throw(
            _(
                "{0} is not a field on {1}. Item Group has {2} (filter it with"
                " `filters`), Item has {3} (filter it with `item_filters`)."
            ).format(fieldname, _(doctype), GIFT_CARD_GROUP_FIELD, GIFT_CARD_ITEM_FIELD),
            frappe.ValidationError,
        )

    frappe.throw(
        _("{0} is not a valid {1} field").format(fieldname, _(doctype)),
        frappe.ValidationError,
    )


def _requested_fields(permitted):
    fields = _parse_json_arg(frappe.form_dict.get("fields"))
    if not fields:
        return ["name"]

    if isinstance(fields, str):
        fields = [fields]

    # "*" is passed through untouched so the wildcard returns exactly the columns
    # it always did. It is the only expression allowed: every other entry has to
    # be a plain Item Group fieldname, which is what keeps subqueries and SQL
    # functions out of the select list.
    if any(field == "*" for field in fields):
        return ["*"]

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


def _gift_card_group_filter():
    """`custom_is_gift_card` as a top level request parameter.

    Absent means no filter at all, so the default result is unchanged. `1`
    returns only gift card groups, `0` only the rest. The same field also works
    inside `filters`; this shorthand matches how `custom_combined_section` is
    passed for the Item side.
    """
    raw = frappe.form_dict.get(GIFT_CARD_GROUP_FIELD)
    if raw in (None, ""):
        return None

    if not _field_exists(ITEM_GROUP_DOCTYPE, GIFT_CARD_GROUP_FIELD):
        frappe.throw(
            _("{0} is not a field on {1} on this site").format(
                GIFT_CARD_GROUP_FIELD, _(ITEM_GROUP_DOCTYPE)
            ),
            frappe.ValidationError,
        )

    return [GIFT_CARD_GROUP_FIELD, "=", cint(raw)]


def _validate_item_filters(caller_filters):
    """Check caller supplied Item filters before they reach the query builder.

    Without this an unknown fieldname surfaces as
    `Unknown column 'tabItem.x' in 'WHERE'` -- a 500 rather than a message the
    caller can act on.
    """
    permitted = _permitted_fieldnames(ITEM_DOCTYPE)
    for filter_row in caller_filters:
        if not isinstance(filter_row, (list, tuple)) or len(filter_row) != 3:
            frappe.throw(
                _("Each item filter must be [field, operator, value]"),
                frappe.ValidationError,
            )
        _validate_fieldname(filter_row[0], permitted, doctype=ITEM_DOCTYPE)


def _build_item_filters():
    """Filters for the Item query that decides which groups have sellable items."""
    caller_filters = frappe.form_dict.get("item_filters")

    if isinstance(caller_filters, str):
        caller_filters = frappe.parse_json(caller_filters) if caller_filters.strip() else None
    if caller_filters is not None and not isinstance(caller_filters, list):
        caller_filters = None

    if caller_filters:
        _validate_item_filters(caller_filters)

    # Historical quirk, kept deliberately: the website default only applies when
    # `item_filters` is sent but unusable, never when it is omitted.
    if caller_filters is None and "item_filters" in frappe.form_dict:
        caller_filters = [["custom_is_website_item", "=", "1"]]

    item_filters = list(caller_filters or []) + [
        ["variant_of", "is", "not set"],
        ["disabled", "=", 0],
    ]

    combined_section = frappe.form_dict.get("custom_combined_section")
    if combined_section:
        item_filters.append(["custom_combined_section", "like", f"%{combined_section}%"])

    return item_filters


def _candidate_group_names():
    """Item groups that hold at least one sellable item and are visible now."""
    group_names = set(
        frappe.get_all(
            ITEM_DOCTYPE,
            filters=_build_item_filters(),
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

    # Visibility is resolved before the list query rather than after it, so a
    # paged request no longer returns short pages.
    return get_visible_item_group_names(sorted(group_names))


@frappe.whitelist(allow_guest=True)
def get_item_group_list():
    """Item groups that currently have sellable items.

    Request arguments (all optional):
        filters                   Item Group filters, including custom_is_gift_card
        custom_is_gift_card       shorthand for the same field: 1 for gift card
                                  groups only, 0 for everything else, omit for all
        item_filters              extra filters for the underlying Item query
        custom_combined_section   match items by combined section
        fields, order_by, limit_start, limit_page_length

    Anything else in the request is ignored.
    """
    group_names = _candidate_group_names()
    if not group_names:
        return []

    permitted = _permitted_fieldnames()
    limit_start, limit_page_length = _page_args()

    filters = _requested_filters(permitted)
    gift_card_filter = _gift_card_group_filter()
    if gift_card_filter:
        filters.append(gift_card_filter)

    query_args = {
        "filters": filters + [["name", "in", group_names]],
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
