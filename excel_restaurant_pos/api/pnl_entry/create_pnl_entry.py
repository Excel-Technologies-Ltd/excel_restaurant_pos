"""Create PnL Entry with multiple attachments in one request."""

import frappe
from frappe import _

from .helpers import (
	append_attachments,
	apply_pnl_entry_fields,
	collect_uploaded_attachment_urls,
	format_pnl_entry_response,
	get_request_data,
	link_files_to_doc,
	parse_bool,
	validate_required_fields,
)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_pnl_entry():
	"""
	Create a draft PnL Entry with income/expense rows and file attachments.

	Use ``multipart/form-data`` and send files under ``attachments``.
	Entry fields can be sent as normal form fields or as one JSON string in ``data``.

	Required
	--------
	company, pnl_type

	Optional
	--------
	posting_date, posting_time, notes, income_items, expense_items, submit

	Example (curl)
	--------------
	curl -X POST https://site/api/method/api.pnl.create \\
	  -H "Authorization: token key:secret" \\
	  -F 'data={"company":"My Company","pnl_type":"Expense","expense_items":[{"type":"COGS","sub_type":"Food","amount":100}]}' \\
	  -F "attachments=@/path/receipt-1.pdf" \\
	  -F "attachments=@/path/receipt-2.jpg"
	"""
	data = get_request_data()
	validate_required_fields(data, ["company", "pnl_type"])

	if data.get("pnl_type") not in ("Income", "Expense"):
		frappe.throw(_("pnl_type must be 'Income' or 'Expense'"), frappe.ValidationError)

	attachment_urls = collect_uploaded_attachment_urls()

	doc = frappe.new_doc("PnL Entry")
	apply_pnl_entry_fields(doc, data, is_create=True)
	append_attachments(doc, attachment_urls)

	doc.insert()
	link_files_to_doc(doc, attachment_urls)

	if parse_bool(data.get("submit")):
		doc.submit()

	frappe.db.commit()
	doc.reload()
	return format_pnl_entry_response(doc)
