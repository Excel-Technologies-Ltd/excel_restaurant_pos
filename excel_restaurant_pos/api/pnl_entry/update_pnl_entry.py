"""Update PnL Entry and manage attachments in one request."""

import frappe
from frappe import _

from .helpers import (
	append_attachments,
	apply_pnl_entry_fields,
	collect_attachment_urls,
	delete_attachment_row,
	ensure_draft,
	format_pnl_entry_response,
	get_request_data,
	parse_bool,
	parse_list,
	validate_required_fields,
)


@frappe.whitelist(allow_guest=False, methods=["PUT", "POST"])
def update_pnl_entry():
	"""
	Update a draft PnL Entry and add/remove attachments.

	JSON / form fields
	------------------
	name                                           (required)
	posting_date, posting_time, company, pnl_type, notes
	income_items, expense_items                    (optional arrays, replaces table when sent)
	pnl_attachments                                (optional, new attachments to append)
	remove_attachments                             (optional array of child row names)
	delete_removed_files                           (optional, 0|1 — delete File docs for removed rows)
	submit                                         (optional, 0|1)

	Multipart upload
	----------------
	Send new files under the field name ``attachments``.
	"""
	data = get_request_data()
	validate_required_fields(data, ["name"])

	doc = frappe.get_doc("PnL Entry", data.get("name"))
	ensure_draft(doc)

	if data.get("pnl_type") and data.get("pnl_type") not in ("Income", "Expense"):
		frappe.throw(_("pnl_type must be 'Income' or 'Expense'"), frappe.ValidationError)

	delete_removed_files = parse_bool(data.get("delete_removed_files"))
	for row_name in parse_list(data.get("remove_attachments")):
		delete_attachment_row(doc, row_name, delete_file=delete_removed_files)

	apply_pnl_entry_fields(doc, data, is_create=False)
	append_attachments(doc, collect_attachment_urls(data))

	doc.save()
	if parse_bool(data.get("submit")):
		doc.submit()

	frappe.db.commit()
	doc.reload()
	return format_pnl_entry_response(doc)
