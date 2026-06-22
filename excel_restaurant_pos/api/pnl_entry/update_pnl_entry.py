"""Update PnL Entry and manage attachments in one request."""

import frappe
from frappe import _

from .helpers import (
	append_attachments,
	apply_pnl_entry_fields,
	collect_uploaded_attachment_urls,
	delete_attachment_row,
	ensure_draft,
	format_pnl_entry_response,
	get_request_data,
	link_files_to_doc,
	parse_bool,
	parse_list,
	validate_required_fields,
)


@frappe.whitelist(allow_guest=False, methods=["PUT", "POST"])
def update_pnl_entry():
	"""
	Update a draft PnL Entry and append/remove file attachments.

	Use ``multipart/form-data`` and send new files under ``attachments``.
	Entry fields can be sent as normal form fields or as one JSON string in ``data``.

	Required
	--------
	name

	Optional
	--------
	posting_date, posting_time, company, pnl_type, notes
	income_items, expense_items, remove_attachments, delete_removed_files, submit

	Example (curl)
	--------------
	curl -X POST https://site/api/method/api.pnl.update \\
	  -H "Authorization: token key:secret" \\
	  -F 'data={"name":"PNL-2026-0001","notes":"Updated","remove_attachments":["child-row-name"],"delete_removed_files":1}' \\
	  -F "attachments=@/path/new-receipt.pdf"
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

	attachment_urls = collect_uploaded_attachment_urls()

	apply_pnl_entry_fields(doc, data, is_create=False)
	append_attachments(doc, attachment_urls)

	doc.save()
	link_files_to_doc(doc, attachment_urls)

	if parse_bool(data.get("submit")):
		doc.submit()

	frappe.db.commit()
	doc.reload()
	return format_pnl_entry_response(doc)
