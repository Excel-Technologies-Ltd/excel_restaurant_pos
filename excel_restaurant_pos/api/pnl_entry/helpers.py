"""Shared helpers for PnL Entry API endpoints."""

import frappe
from frappe import _
from frappe.utils import cint, nowdate, nowtime


INCOME_ITEM_FIELDS = ("type", "sub_type", "amount", "description")
EXPENSE_ITEM_FIELDS = ("type", "sub_type", "amount", "description")


def get_request_data():
	"""Return a mutable dict from the current request payload."""
	data = dict(frappe.form_dict)
	for key in ("cmd", "data"):
		data.pop(key, None)
	return data


def parse_list(value):
	if value is None:
		return []
	if isinstance(value, str):
		return frappe.parse_json(value) or []
	if isinstance(value, list):
		return value
	return []


def parse_bool(value, default=False):
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	return cint(value) == 1


def pick_row_fields(row, allowed_fields):
	if not isinstance(row, dict):
		frappe.throw(_("Each child row must be an object"))
	return {field: row.get(field) for field in allowed_fields if row.get(field) is not None}


def validate_required_fields(data, fields):
	for field in fields:
		if not data.get(field):
			frappe.throw(_("{0} is required").format(field), frappe.MandatoryError)


def ensure_draft(doc):
	if doc.docstatus != 0:
		frappe.throw(_("Only draft PnL Entries can be modified"), frappe.ValidationError)


def normalize_attachment_url(value):
	if isinstance(value, dict):
		value = value.get("attachment")
	if not value:
		return None
	return str(value).strip()


def save_uploaded_file(uploaded_file, is_private=1):
	if not uploaded_file:
		return None

	file_content = uploaded_file.stream.read()
	if not file_content:
		frappe.throw(_("Uploaded file is empty"), frappe.ValidationError)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": uploaded_file.filename,
			"content": file_content,
			"is_private": cint(is_private),
		}
	)
	file_doc.insert(ignore_permissions=True)
	return file_doc.file_url


def collect_attachment_urls(data):
	"""Collect attachment file URLs from JSON payload and multipart uploads."""
	urls = []

	for item in parse_list(data.get("pnl_attachments")):
		url = normalize_attachment_url(item)
		if url:
			urls.append(url)

	request_files = getattr(frappe.request, "files", None)
	if request_files:
		uploaded_files = request_files.getlist("attachments")
		for uploaded_file in uploaded_files:
			url = save_uploaded_file(uploaded_file)
			if url:
				urls.append(url)

	return urls


def append_attachments(doc, attachment_urls):
	for url in attachment_urls:
		doc.append("pnl_attachments", {"attachment": url})


def set_child_rows(doc, fieldname, rows, allowed_fields):
	doc.set(fieldname, [])
	for row in rows:
		doc.append(fieldname, pick_row_fields(row, allowed_fields))


def apply_pnl_entry_fields(doc, data, is_create=False):
	if is_create:
		doc.posting_date = data.get("posting_date") or nowdate()
		doc.posting_time = data.get("posting_time") or nowtime()
		doc.company = data.get("company")
		doc.pnl_type = data.get("pnl_type")
	else:
		for field in ("posting_date", "posting_time", "company", "pnl_type", "notes"):
			if data.get(field) is not None:
				doc.set(field, data.get(field))

	if "income_items" in data:
		set_child_rows(doc, "income_items", parse_list(data.get("income_items")), INCOME_ITEM_FIELDS)

	if "expense_items" in data:
		set_child_rows(doc, "expense_items", parse_list(data.get("expense_items")), EXPENSE_ITEM_FIELDS)


def format_pnl_entry_response(doc):
	return {
		"name": doc.name,
		"posting_date": doc.posting_date,
		"posting_time": doc.posting_time,
		"company": doc.company,
		"pnl_type": doc.pnl_type,
		"notes": doc.notes,
		"docstatus": doc.docstatus,
		"total_income": doc.total_income,
		"total_expense": doc.total_expense,
		"net_profit_loss": doc.net_profit_loss,
		"income_items": [row.as_dict() for row in (doc.income_items or [])],
		"expense_items": [row.as_dict() for row in (doc.expense_items or [])],
		"pnl_attachments": [row.as_dict() for row in (doc.pnl_attachments or [])],
	}


def delete_attachment_row(doc, attachment_row_name, delete_file=False):
	row = next((item for item in (doc.pnl_attachments or []) if item.name == attachment_row_name), None)
	if not row:
		frappe.throw(_("Attachment row not found on this PnL Entry"), frappe.DoesNotExistError)

	file_url = row.attachment
	doc.remove(row)

	if delete_file and file_url:
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if file_name:
			frappe.delete_doc("File", file_name, ignore_permissions=True)
