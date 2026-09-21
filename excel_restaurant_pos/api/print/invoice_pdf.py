"""Sales Invoice PDF download for the Order Web."""

import frappe

from excel_restaurant_pos.shared.print_format.invoice_pdf import build_pdf_response
from excel_restaurant_pos.shared.customer_access import access_level, require_login


def _get_invoice_name() -> str:
	"""Resolve the invoice name from the query string or a JSON body."""
	form = frappe.form_dict
	return (
		form.get("invoice_name")
		or form.get("invoice_number")
		or form.get("sales_invoice")
		or form.get("name")
		or ""
	)


def _get_format_key() -> str:
	"""Resolve which of the configured formats the caller asked for."""
	form = frappe.form_dict
	return (
		form.get("format")
		or form.get("print_format")
		or form.get("format_type")
		or ""
	)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def invoice_pdf():
	"""
	Download a Sales Invoice as a PDF, rendered with a configured print format.

	The caller says which one. Only the two formats ArcPOS Settings holds are
	available, so the storefront chooses between the restaurant's own formats
	and cannot render an invoice through an arbitrary one.

	Owner or staff only (shared/customer_access.py). It used to be public, so
	anyone could download any order's receipt by guessing its sequential number.
	Throttled at 30 renders per caller per minute, since building a PDF is real
	work.

	Request
	-------
	invoice_name (required): Sales Invoice name. `invoice_number`,
	    `sales_invoice` and `name` are accepted as aliases.
	format (optional): which configured format to render.
	    `default`  -> ArcPOS Settings > Default Print Format (the default)
	    `delivery` -> ArcPOS Settings > Default Delivery Print Format
	    `print_format` and `format_type` are accepted as aliases. An
	    unrecognised value is refused rather than silently served as `default`.

	Response
	--------
	The PDF as an attachment. `X-Print-Format` names the Print Format that
	rendered it and `X-Print-Format-Key` echoes the key it came from; both, and
	`Content-Disposition`, are readable cross origin.

	It needs the caller's bearer token, so fetch it (order-web's
	downloadInvoicePdf does) -- a plain `window.location` navigation cannot
	carry the header and is refused.
	"""
	require_login()
	invoice_name = _get_invoice_name()
	if invoice_name:
		access_level(invoice_name)
	return build_pdf_response(invoice_name, _get_format_key())
