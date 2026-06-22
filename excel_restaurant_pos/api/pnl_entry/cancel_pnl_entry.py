"""Cancel a submitted PnL Entry."""

import frappe
from frappe import _

from .helpers import (
	ensure_submitted,
	format_pnl_entry_response,
	get_request_data,
	validate_required_fields,
)


@frappe.whitelist(allow_guest=False, methods=["POST", "PUT"])
def cancel_pnl_entry(name=None):
	"""
	Cancel a submitted PnL Entry.

	Required
	--------
	name — PnL Entry name (e.g. INC-2026-0001 or EXP-2026-0001)

	Example
	-------
	curl -X POST https://site/api/method/api.pnl.cancel \\
	  -H "Authorization: token key:secret" \\
	  -H "Content-Type: application/json" \\
	  -d '{"name": "EXP-2026-0001"}'
	"""
	data = get_request_data()
	entry_name = name or data.get("name")
	if not entry_name:
		frappe.throw(_("name is required"), frappe.MandatoryError)

	validate_required_fields({"name": entry_name}, ["name"])

	doc = frappe.get_doc("PnL Entry", entry_name)
	ensure_submitted(doc)
	doc.cancel()

	frappe.db.commit()
	doc.reload()
	return format_pnl_entry_response(doc)
