from .get_sales_summery import get_sales_summery
from .get_item_sales_summery import get_item_sales_summery
from .get_sales_by_service_type import get_sales_by_service_type
from .get_pnl_report import get_pnl_report, get_pnl_categories
from .get_employee_timeclock_summary import get_employee_timeclock_summary

__all__ = [
    "get_sales_summery",
    "get_item_sales_summery",
    "get_sales_by_service_type",
    "get_pnl_report",
    "get_pnl_categories",
    "get_employee_timeclock_summary",
]

report_api_routes = {
    "api.reports.get_sales_summery": "excel_restaurant_pos.api.report.get_sales_summery.get_sales_summery",
    "api.reports.get_item_sales_summery": "excel_restaurant_pos.api.report.get_item_sales_summery.get_item_sales_summery",
    "api.reports.sales_by_service": "excel_restaurant_pos.api.report.get_sales_by_service_type.get_sales_by_service_type",
    "api.reports.get_pnl_report": "excel_restaurant_pos.api.report.get_pnl_report.get_pnl_report",
    "api.reports.get_pnl_categories": "excel_restaurant_pos.api.report.get_pnl_report.get_pnl_categories",
    "api.reports.employee_timeclock_summary": "excel_restaurant_pos.api.report.get_employee_timeclock_summary.get_employee_timeclock_summary",
}
