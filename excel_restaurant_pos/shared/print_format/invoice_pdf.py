"""Sales Invoice PDF rendering for the Order Web.

The caller says which of the two configured formats it wants -- `default` for
ArcPOS Settings *Default Print Format*, `delivery` for *Default Delivery Print
Format*. Only those two keys are accepted, so the storefront chooses between the
restaurant's own formats and cannot render an invoice through an arbitrary one.

Deliberately not inferred from the invoice's service type: a delivery order may
legitimately need the customer receipt, and a pickup order the delivery slip.
Guessing from the document takes that choice away from the caller.

The finished PDF is streamed as an attachment with the same response discipline
as the timeclock export: never cached, never sniffed, and with the headers a
cross origin SPA needs to read the filename.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

SETTINGS_DOCTYPE = "ArcPOS Settings"
INVOICE_DOCTYPE = "Sales Invoice"

PDF_MIMETYPE = "application/pdf"
FALLBACK_PRINT_FORMAT = "Standard"

# The format key a caller may ask for -> the ArcPOS Settings field holding it.
FORMAT_FIELDS = {
	"default": "print_format_for_order",
	"delivery": "default_delivery_pf",
}
DEFAULT_FORMAT_KEY = "default"

# Rendering a PDF costs real CPU, and this route is reachable without a login.
PDF_RATE_LIMIT = 30
PDF_RATE_WINDOW = 60

# Frappe's CORS handling sets Allow-Origin but never Expose-Headers, so a cross
# origin fetch() could otherwise read the body but not the filename.
EXPOSED_HEADERS = "Content-Disposition, Content-Length, X-Print-Format, X-Print-Format-Key"


def parse_format_key(value) -> str:
	"""Normalise the requested format key, defaulting to the standard receipt.

	An unrecognised key is refused rather than quietly served as the default:
	asking for a format that does not exist should not hand back a different
	document without saying so.
	"""
	key = (value or "").strip().lower()
	if not key:
		return DEFAULT_FORMAT_KEY

	if key not in FORMAT_FIELDS:
		frappe.throw(
			_("Unknown print format {0}. Use one of: {1}.").format(
				value, ", ".join(sorted(FORMAT_FIELDS))
			),
			frappe.ValidationError,
		)

	return key


def resolve_print_format(format_key: str = DEFAULT_FORMAT_KEY) -> str:
	"""The Print Format configured in ArcPOS Settings for this key.

	Falls back to Frappe's Standard format rather than throwing: a customer
	downloading their own receipt should not be blocked by a setting nobody
	filled in, and Standard renders every field that matters.
	"""
	fieldname = FORMAT_FIELDS[parse_format_key(format_key)]
	print_format = (frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname) or "").strip()

	if not print_format:
		return FALLBACK_PRINT_FORMAT

	# The setting is a Link, but a format can be renamed or deleted after it was
	# chosen; rendering would then fail with a confusing template error.
	if not frappe.db.exists("Print Format", print_format):
		frappe.log_error(
			f"ArcPOS Settings.{fieldname} points at missing Print Format {print_format!r}",
			"Invoice PDF print format missing",
		)
		return FALLBACK_PRINT_FORMAT

	return print_format


def get_invoice(invoice_name: str):
	"""Load the invoice a PDF was asked for."""
	invoice_name = (invoice_name or "").strip()
	if not invoice_name:
		frappe.throw(_("Invoice name is required"), frappe.MandatoryError)

	if not frappe.db.exists(INVOICE_DOCTYPE, invoice_name):
		frappe.throw(_("Invoice {0} not found").format(invoice_name), frappe.DoesNotExistError)

	invoice = frappe.get_doc(INVOICE_DOCTYPE, invoice_name)

	if cint(invoice.docstatus) == 2:
		frappe.throw(_("Order {0} was cancelled.").format(invoice.name), frappe.ValidationError)

	return invoice


def pdf_filename(invoice) -> str:
	"""Attachment name the browser saves it under."""
	return f"{invoice.name}.pdf"


def render_pdf(invoice, print_format: str) -> bytes:
	"""Render the invoice through a print format.

	`no_letterhead=0` keeps whatever letterhead the format itself defines.

	wkhtmltopdf failures surface as a bare OSError carrying its stderr -- most
	often it could not fetch an asset the format references by absolute URL, so
	the message names the site host and means nothing to a customer. Translate
	it, and keep the real one in the error log where it can be acted on.
	"""
	try:
		return frappe.get_print(
			INVOICE_DOCTYPE,
			invoice.name,
			print_format=print_format,
			doc=invoice,
			as_pdf=True,
			no_letterhead=0,
		)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Invoice PDF render failed: {invoice.name} via {print_format}",
		)
		frappe.throw(
			_("Could not produce the PDF for order {0}. Please try again.").format(invoice.name),
			frappe.ValidationError,
		)


def build_pdf_response(invoice_name: str, format_key: str = DEFAULT_FORMAT_KEY):
	"""Permission free, rate limited PDF download for the Order Web.

	Reachable without a Frappe session on purpose: the storefront is public and
	a customer has no Desk login. It exposes nothing that
	`api.sales_invoices.get` -- guest reachable, returns the whole invoice --
	does not already expose.
	"""
	from werkzeug.wrappers import Response

	from excel_restaurant_pos.utils.rate_limit import rate_limit_by_caller

	rate_limit_by_caller("invoice_pdf", limit=PDF_RATE_LIMIT, seconds=PDF_RATE_WINDOW)

	# Parsed before the invoice is loaded, so a bad key fails on its own terms
	# rather than after the work of fetching a document.
	format_key = parse_format_key(format_key)

	invoice = get_invoice(invoice_name)
	print_format = resolve_print_format(format_key)
	content = render_pdf(invoice, print_format)

	response = Response(content, mimetype=PDF_MIMETYPE)
	response.headers.add("Content-Disposition", "attachment", filename=pdf_filename(invoice))
	response.headers["Content-Length"] = str(len(content))
	# Tells the caller which format rendered it, so a mis-set setting is visible
	# from the response rather than only from the PDF itself.
	response.headers["X-Print-Format"] = print_format
	# Echoes the key back, so a caller can confirm which of the two it got
	# without knowing what the settings are named.
	response.headers["X-Print-Format-Key"] = format_key
	# A receipt carries the customer's name, address and phone: never let a
	# proxy or the browser keep a copy.
	response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
	response.headers["X-Content-Type-Options"] = "nosniff"
	response.headers["Access-Control-Expose-Headers"] = EXPOSED_HEADERS
	response.headers["Referrer-Policy"] = "no-referrer"
	return response
