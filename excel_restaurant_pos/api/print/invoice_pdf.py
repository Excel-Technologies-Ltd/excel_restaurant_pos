"""Sales Invoice PDF download for the Order Web."""

import frappe

from excel_restaurant_pos.shared.print_format.invoice_pdf import build_pdf_response


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


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def invoice_pdf():
	"""
	Download a Sales Invoice as a PDF, rendered with the configured print format.

	The format is chosen from ArcPOS Settings by service type -- *Default
	Delivery Print Format* for a delivery order, *Default Print Format*
	otherwise -- and is never taken from the caller.

	Guest reachable, because the storefront is public and a customer has no
	Frappe login. It exposes nothing `api.sales_invoices.get` does not already.
	Throttled at 30 renders per caller per minute, since building a PDF is real
	work.

	Request
	-------
	invoice_name (required): Sales Invoice name. `invoice_number`,
	    `sales_invoice` and `name` are accepted as aliases.

	Response
	--------
	The PDF as an attachment. `X-Print-Format` names the format that rendered
	it; both it and `Content-Disposition` are readable cross origin.

	Because it is a plain GET with no header requirement, the browser can be
	sent straight at it:

	    window.location = `${API}/api/method/api.print.invoice_pdf`
	      + `?invoice_name=${encodeURIComponent(invoiceName)}`;
	"""
	return build_pdf_response(_get_invoice_name())
