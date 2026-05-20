import frappe
from frappe.utils import add_days
from .report_helper import (
    validate_required_yyyy_mm_dd,
    validate_start_end_date,
)


@frappe.whitelist(allow_guest=True)
def get_sales_summery():
    """
    Get sales summary report.

    Args:
        start_date: Report start date (YYYY-MM-DD). Required.
        end_date: Report end date (YYYY-MM-DD). Required.
    """
    data = frappe.form_dict or {}
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    start_date = validate_required_yyyy_mm_dd("Start Date", start_date)
    end_date = validate_required_yyyy_mm_dd("End Date", end_date)
    validate_start_end_date(start_date, end_date)

    # DB function likely treats end_date as exclusive (< end_date).
    # To make the API behave inclusive, pass end_date + 1 day.
    # end_date_for_query = add_days(end_date, 1)
    values = {"start_date": start_date, "end_date": end_date}

    try:
        # SQL function-style call (often returns JSON text)
        rows = frappe.db.sql(
            "SELECT `get_Sales Summary`(%(start_date)s, %(end_date)s) AS `data`",
            values=values,
            as_dict=True,
        )

        data = (rows or [{}])[0].get("data")
        if data is None:
            return None

        # If function returns JSON string, parse to dict/list
        if isinstance(data, str):
            return frappe.parse_json(data)

        return data
    except Exception:
        frappe.log_error(
            title="get_sales_summery failed",
            message=frappe.get_traceback(),
        )
        frappe.throw(
            frappe._(
                "Failed to fetch Sales Summary. Please contact your system administrator."
            ),
            frappe.ValidationError,
        )
