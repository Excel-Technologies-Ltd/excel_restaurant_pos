"""Shared helpers for PnL Entry API endpoints."""

import frappe
from frappe import _
from frappe.utils import cint, get_url, nowdate, nowtime

from excel_restaurant_pos.excel_restaurant_pos.doctype.pnl_entry.pnl_entry import (
	get_naming_series_for_pnl_type,
)


INCOME_ITEM_FIELDS = ("type", "sub_type", "amount", "description")
EXPENSE_ITEM_FIELDS = ("type", "sub_type", "amount", "description")
JSON_LIST_FIELDS = ("income_items", "expense_items", "remove_attachments")
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
ALLOWED_ATTACHMENT_TYPES = {
	"application/pdf",
	"image/jpeg",
	"image/jpg",
	"image/png",
	"image/webp",
	"image/heic",
	"image/heif",
}


def get_request_data():
	"""
	Parse request payload for JSON or multipart/form-data.

	Multipart clients can send all entry fields in a JSON string field named
	``data`` and upload files under ``attachments``.
	"""
	data = dict(frappe.form_dict)
	data.pop("cmd", None)

	bundled = data.pop("data", None)
	if bundled:
		payload = frappe.parse_json(bundled)
		if isinstance(payload, dict):
			data.update(payload)

	for field in JSON_LIST_FIELDS:
		if field in data:
			data[field] = parse_list(data.get(field))

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
	if isinstance(value, (int, float)):
		return cint(value) == 1
	if isinstance(value, str):
		normalized = value.strip().lower()
		if normalized in ("1", "true", "yes", "on"):
			return True
		if normalized in ("0", "false", "no", "off", ""):
			return False
	return cint(value) == 1


def resolve_submit_flag(explicit_submit=None, data=None):
	if parse_bool(explicit_submit):
		return True
	if data:
		return parse_bool(data.get("submit"))
	return False


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


def ensure_submitted(doc):
	if doc.docstatus != 1:
		frappe.throw(_("Only submitted PnL Entries can be cancelled"), frappe.ValidationError)


def _get_uploaded_files():
	request_files = getattr(frappe.request, "files", None)
	if not request_files:
		return []

	uploaded_files = []
	for fieldname in ("attachments", "attachments[]", "attachment"):
		uploaded_files.extend(request_files.getlist(fieldname))

	if not uploaded_files:
		for fieldname in ("attachments", "attachment"):
			single_file = request_files.get(fieldname)
			if single_file:
				uploaded_files.append(single_file)

	# Deduplicate while preserving order (some clients send the same file twice).
	seen = set()
	unique_files = []
	for uploaded_file in uploaded_files:
		file_id = id(uploaded_file)
		if file_id in seen:
			continue
		seen.add(file_id)
		unique_files.append(uploaded_file)

	return unique_files


def save_uploaded_file(uploaded_file, is_private=0):
	if not uploaded_file:
		return None

	content_type = (uploaded_file.content_type or "").split(";")[0].strip().lower()
	if content_type and content_type not in ALLOWED_ATTACHMENT_TYPES:
		frappe.throw(
			_("File type {0} is not allowed. Allowed types: PDF and images.").format(
				uploaded_file.content_type
			),
			frappe.ValidationError,
		)

	file_content = uploaded_file.stream.read()
	if not file_content:
		frappe.throw(_("Uploaded file is empty"), frappe.ValidationError)

	if len(file_content) > MAX_ATTACHMENT_SIZE:
		frappe.throw(
			_("File {0} is too large. Maximum size is 10 MB.").format(uploaded_file.filename),
			frappe.ValidationError,
		)

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


def collect_uploaded_attachment_urls():
	"""Save multipart files from the current request and return their file URLs."""
	urls = []
	for uploaded_file in _get_uploaded_files():
		url = save_uploaded_file(uploaded_file)
		if url:
			urls.append(url)
	return urls


def link_files_to_doc(doc, file_urls):
	for file_url in file_urls:
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not file_name:
			continue

		frappe.db.set_value(
			"File",
			file_name,
			{
				"attached_to_doctype": doc.doctype,
				"attached_to_name": doc.name,
			},
		)


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

	if doc.is_new() and doc.pnl_type:
		doc.naming_series = get_naming_series_for_pnl_type(doc.pnl_type)

	if "income_items" in data:
		set_child_rows(doc, "income_items", parse_list(data.get("income_items")), INCOME_ITEM_FIELDS)

	if "expense_items" in data:
		set_child_rows(doc, "expense_items", parse_list(data.get("expense_items")), EXPENSE_ITEM_FIELDS)


def format_attachment_row(row):
	row_dict = row.as_dict()
	if row.attachment:
		row_dict["attachment_url"] = get_url(row.attachment)
	return row_dict


def format_pnl_entry_response(doc):
	return {
		"name": doc.name,
		"naming_series": doc.naming_series,
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
		"pnl_attachments": [format_attachment_row(row) for row in (doc.pnl_attachments or [])],
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
