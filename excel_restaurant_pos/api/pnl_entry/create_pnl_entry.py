"""Create PnL Entry with multiple attachments in one request."""

import frappe
from frappe import _

from .helpers import (
	append_attachments,
	apply_pnl_entry_fields,
	collect_attachment_urls,
	format_pnl_entry_response,
	get_request_data,
	parse_bool,
	validate_required_fields,
)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_pnl_entry():
	"""
	Create a draft PnL Entry with income/expense rows and attachments.

	JSON / form fields
	------------------
	posting_date, posting_time, company, pnl_type  (required)
	notes                                          (optional)
	income_items, expense_items                    (optional arrays)
	pnl_attachments                                (optional array of { "attachment": "/files/..." })
	submit                                         (optional, 0|1)

	Multipart upload
	----------------
	Send files under the field name ``attachments`` together with the same payload.
	"""
	data = get_request_data()
	validate_required_fields(data, ["company", "pnl_type"])

	if data.get("pnl_type") not in ("Income", "Expense"):
		frappe.throw(_("pnl_type must be 'Income' or 'Expense'"), frappe.ValidationError)

	doc = frappe.new_doc("PnL Entry")
	apply_pnl_entry_fields(doc, data, is_create=True)
	append_attachments(doc, collect_attachment_urls(data))

	doc.insert()
	if parse_bool(data.get("submit")):
		doc.submit()

	frappe.db.commit()
	doc.reload()
	return format_pnl_entry_response(doc)
