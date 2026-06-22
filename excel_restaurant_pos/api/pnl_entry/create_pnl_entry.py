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
	resolve_submit_flag,
	validate_required_fields,
)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_pnl_entry(submit=0):
	"""
	Create a PnL Entry with income/expense rows and file attachments.

	Use ``multipart/form-data`` and send files under ``attachments``.
	Entry fields can be sent as normal form fields or as one JSON string in ``data``.

	Required
	--------
	company, pnl_type

	Optional
	--------
	posting_date, posting_time, notes
	income_items   — use when pnl_type is "Income"
	expense_items  — use when pnl_type is "Expense"
	submit (0|1|true|false) — save as draft by default; pass 1 to submit immediately

	Child row fields
	----------------
	type, sub_type, amount, description

	Example — Expense entry
	-----------------------
	curl -X POST https://site/api/method/api.pnl.create \\
	  -H "Authorization: token key:secret" \\
	  -F 'data={"company":"My Company","pnl_type":"Expense","submit":1,"expense_items":[{"type":"COGS","sub_type":"Food","amount":100}]}' \\
	  -F "attachments=@/path/receipt-1.pdf"

	Example — Income entry
	----------------------
	curl -X POST https://site/api/method/api.pnl.create \\
	  -H "Authorization: token key:secret" \\
	  -F 'data={"company":"My Company","pnl_type":"Income","submit":1,"income_items":[{"type":"Sales","sub_type":"Dine In","amount":500,"description":"Lunch sales"}]}' \\
	  -F "attachments=@/path/receipt-1.pdf"
	"""
	data = get_request_data()
	validate_required_fields(data, ["company", "pnl_type"])

	if data.get("pnl_type") not in ("Income", "Expense"):
		frappe.throw(_("pnl_type must be 'Income' or 'Expense'"), frappe.ValidationError)

	attachment_urls = collect_uploaded_attachment_urls()
	should_submit = resolve_submit_flag(submit, data)

	doc = frappe.new_doc("PnL Entry")
	apply_pnl_entry_fields(doc, data, is_create=True)
	append_attachments(doc, attachment_urls)

	doc.insert()
	link_files_to_doc(doc, attachment_urls)

	if should_submit:
		doc.submit()

	frappe.db.commit()
	doc.reload()
	return format_pnl_entry_response(doc)
