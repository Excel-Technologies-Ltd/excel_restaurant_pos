import frappe
from .report_helper import (
    as_int,
    normalize_optional_string,
    validate_required_yyyy_mm_dd,
    validate_start_end_date,
)


def parse_order_by(order_by_value, default_order_by="amount DESC"):
    """
    Parse and validate order_by parameter from frontend.

    Expected format: "field_name ASC" or "field_name DESC" or just "field_name" (defaults to ASC)
    Multiple fields: "field1 DESC, field2 ASC"

    Allowed fields: item_name, item_group, sold_qty, amount

    Returns safe SQL ORDER BY clause string.
    """
    if not order_by_value:
        return default_order_by

    # Allowed fields mapping (frontend name -> SQL expression)
    allowed_fields = {
        "item_name": "TSII.`item_name`",
        "item_group": "TSII.`item_group`",
        "sold_qty": "SUM(COALESCE(TSII.`qty`, 0))",
        "amount": "SUM(COALESCE(TSII.`amount`, 0))",
    }

    # Parse order_by - could be string or JSON array
    if isinstance(order_by_value, str):
        # Try to parse as JSON first (in case it's a JSON string)
        try:
            parsed = frappe.parse_json(order_by_value)
            if isinstance(parsed, list):
                order_parts = [str(part).strip() for part in parsed]
            else:
                order_parts = [str(parsed).strip()]
        except Exception:
            # Not JSON, treat as comma-separated string
            order_parts = [part.strip() for part in order_by_value.split(",")]
    elif isinstance(order_by_value, list):
        order_parts = [str(part).strip() for part in order_by_value]
    else:
        order_parts = [str(order_by_value).strip()]

    order_clauses = []
    for part in order_parts:
        if not part:
            continue

        # Split by space to get field and direction
        tokens = part.strip().split()
        field_name = tokens[0].lower()
        direction = tokens[1].upper() if len(tokens) > 1 else "ASC"

        # Validate field name
        if field_name not in allowed_fields:
            frappe.throw(
                frappe._("Invalid order_by field: {0}. Allowed fields: {1}").format(
                    field_name, ", ".join(allowed_fields.keys())
                ),
                frappe.ValidationError,
            )

        # Validate direction
        if direction not in ["ASC", "DESC"]:
            frappe.throw(
                frappe._("Invalid order_by direction: {0}. Must be ASC or DESC").format(
                    direction
                ),
                frappe.ValidationError,
            )

        order_clauses.append(f"{allowed_fields[field_name]} {direction}")

    if not order_clauses:
        return default_order_by

    return ", ".join(order_clauses)


@frappe.whitelist()
def get_item_sales_summery():
    """
    Get item performance summary (same output as `get_Item_Performance` procedure),
    implemented via Frappe SQL with pagination + filters.

    Required args (via request):
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD

    Optional args:
        item_group: string (if not provided, returns all item groups)
        item_name: string (partial match)
        order_by: string (e.g., "amount DESC", "item_name ASC", "sold_qty DESC, item_name ASC")
        limit_start (0-based) + limit / limit_page_length (Frappe style)
    """
    data = frappe.form_dict or {}

    start_date = data.get("start_date") or data.get("from_date")
    end_date = data.get("end_date") or data.get("to_date")
    start_date = validate_required_yyyy_mm_dd("Start Date", start_date)
    end_date = validate_required_yyyy_mm_dd("End Date", end_date)
    validate_start_end_date(start_date, end_date)

    item_group = normalize_optional_string(data.get("item_group"))
    item_name = normalize_optional_string(data.get("item_name"))

    # Parse and validate order_by
    order_by = parse_order_by(
        data.get("order_by"), default_order_by="SUM(COALESCE(TSII.`amount`, 0)) DESC"
    )

    # Frappe-style pagination
    limit_start = as_int("limit_start", data.get("limit_start"), 0)
    if limit_start < 0:
        frappe.throw(frappe._("limit_start cannot be negative"), frappe.ValidationError)

    limit_page_length = as_int(
        "limit",
        data.get("limit") or data.get("limit_page_length") or data.get("page_length"),
        10,
    )
    if limit_page_length <= 0:
        frappe.throw(frappe._("limit must be greater than 0"), frappe.ValidationError)
    # Guardrail against accidental huge payloads
    limit_page_length = min(limit_page_length, 500)

    where_clauses = [
        "TSII.`docstatus` = 1",
        "TI.`docstatus` = 1",
        "TI.`posting_date` >= %(start_date)s",
        "TI.`posting_date` <= %(end_date)s",
    ]

    values = {
        "start_date": start_date,
        "end_date": end_date,
        "limit_start": limit_start,
        "limit_page_length": limit_page_length,
    }

    if item_group:
        where_clauses.append("TSII.`item_group` = %(item_group)s")
        values["item_group"] = item_group

    if item_name:
        # partial match search
        where_clauses.append("TSII.`item_name` LIKE %(item_name)s")
        values["item_name"] = f"%{item_name}%"

    where_sql = " AND ".join(where_clauses)

    try:
        # Total number of grouped rows (for pagination)
        total = frappe.db.sql(
            f"""
            SELECT COUNT(*) AS total
            FROM (
                SELECT TSII.`item_name`, TSII.`item_group`
                FROM `tabSales Invoice Item` TSII
                INNER JOIN `tabSales Invoice` TI ON TSII.`parent` = TI.`name`
                WHERE {where_sql}
                GROUP BY TSII.`item_name`, TSII.`item_group`
            ) t
            """,
            values=values,
            as_dict=True,
        )[0]["total"]

        totals = frappe.db.sql(
            f"""
            SELECT
                SUM(COALESCE(TSII.`qty`, 0)) AS `total_qty`,
                SUM(COALESCE(TSII.`net_amount`, 0)) AS `total_amount`
            FROM `tabSales Invoice Item` TSII
            INNER JOIN `tabSales Invoice` TI ON TSII.`parent` = TI.`name`
            WHERE {where_sql}
            """,
            values=values,
            as_dict=True,
        )[0]

        rows = frappe.db.sql(
            f"""
            SELECT
                TSII.`item_name`,
                TSII.`item_group`,
                SUM(COALESCE(TSII.`qty`, 0)) AS `sold_qty`,
                SUM(COALESCE(TSII.`net_amount`, 0)) AS `amount`
            FROM `tabSales Invoice Item` TSII
            INNER JOIN `tabSales Invoice` TI ON TSII.`parent` = TI.`name`
            WHERE {where_sql}
            GROUP BY TSII.`item_name`, TSII.`item_group`
            ORDER BY {order_by}
            LIMIT %(limit_start)s, %(limit_page_length)s
            """,
            values=values,
            as_dict=True,
        )

        return {
            "data": rows,
            "total": int(total or 0),
            "total_qty": float(totals.get("total_qty") or 0),
            "total_Amount": float(totals.get("total_amount") or 0),
            "limit_start": limit_start,
            "limit": limit_page_length,
        }
    except Exception:
        frappe.log_error(
            title="get_item_sales_summery failed",
            message=frappe.get_traceback(),
        )
        frappe.throw(
            frappe._(
                "Failed to fetch Item Performance. Please contact your system administrator."
            ),
            frappe.ValidationError,
        )
