"""Print / PDF API endpoints."""

from .invoice_pdf import invoice_pdf
from .print import (  # noqa: F401
	get_print_format_sales_invoice,
	get_sales_invoice_print_url,
	get_table_order_print_url,
)

__all__ = [
	"invoice_pdf",
	"get_print_format_sales_invoice",
	"get_sales_invoice_print_url",
	"get_table_order_print_url",
]

print_api_routes = {
	"api.print.invoice_pdf": "excel_restaurant_pos.api.print.invoice_pdf",
}
