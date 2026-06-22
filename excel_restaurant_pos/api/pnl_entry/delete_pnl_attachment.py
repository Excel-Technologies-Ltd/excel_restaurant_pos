"""Delete a single PnL attachment child row."""

import frappe
from frappe import _

from .helpers import (
	delete_attachment_row,
	ensure_draft,
	format_pnl_entry_response,
	get_request_data,
	parse_bool,
	validate_required_fields,
)


@frappe.whitelist(allow_guest=False, methods=["DELETE", "POST"])
def delete_pnl_attachment():
	"""
	Remove one attachment row from a draft PnL Entry.

	Parameters
	----------
	pnl_entry            : PnL Entry name (required)
	attachment_row_name    : child row name from pnl_attachments (required)
	delete_file            : 0|1 — also delete the linked File document (optional)
	"""
	data = get_request_data()
	validate_required_fields(data, ["pnl_entry", "attachment_row_name"])

	doc = frappe.get_doc("PnL Entry", data.get("pnl_entry"))
	ensure_draft(doc)

	delete_attachment_row(
		doc,
		data.get("attachment_row_name"),
		delete_file=parse_bool(data.get("delete_file")),
	)
	doc.save()

	frappe.db.commit()
	doc.reload()
	return format_pnl_entry_response(doc)
