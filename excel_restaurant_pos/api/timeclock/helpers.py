"""Shared helpers for employee timeclock API endpoints."""

import json

import frappe
from frappe import _


def get_request_data() -> dict:
	"""Parse request payload from form fields or JSON body."""
	raw_data = frappe.form_dict.get("data")
	if raw_data:
		if isinstance(raw_data, str):
			return json.loads(raw_data)
		return raw_data

	return dict(frappe.form_dict)


def get_pin(data: dict, fieldname: str = "pin") -> str:
	"""Resolve a PIN from request data."""
	pin = data.get(fieldname) or frappe.form_dict.get(fieldname)
	if not pin:
		frappe.throw(_("{0} is required").format(fieldname), frappe.MandatoryError)
	return str(pin).strip()


def get_remarks(data: dict, fieldname: str = "remarks"):
	"""Resolve the shift note from request data.

	Returns `None` when the caller did not send the key at all, which the
	services read as "leave whatever is stored alone". An empty string is a
	real value and means "clear it", so absence and emptiness cannot be
	collapsed with the usual `or` chain.
	"""
	for source in (data, frappe.form_dict):
		if fieldname in source:
			value = source[fieldname]
			return "" if value is None else str(value)
	return None


def get_business_date_param(data: dict, required: bool = True):
	"""Resolve the business date from request data."""
	business_date = (
		data.get("business_date") or data.get("date") or frappe.form_dict.get("business_date")
	)
	if not business_date and required:
		frappe.throw(_("business_date is required"), frappe.MandatoryError)
	return business_date
