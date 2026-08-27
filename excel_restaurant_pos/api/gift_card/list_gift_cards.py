"""List gift cards (admin) and inactive cards (Existing picker)."""

import frappe

from excel_restaurant_pos.api.coupon.helpers import get_request_data
from excel_restaurant_pos.shared.gift_card.redemption import (
	list_gift_cards as list_gift_cards_service,
	list_inactive_gift_cards as list_inactive_service,
)


@frappe.whitelist(methods=["GET", "POST"])
def list_inactive_gift_cards():
	"""
	Search Inactive gift cards for POS Existing-type picker.

	Request
	-------
	search (optional): code / name fragment
	limit (optional): max rows (default 20, max 100)
	"""
	data = get_request_data()
	search = data.get("search") or frappe.form_dict.get("search") or frappe.request.args.get("search")
	limit = data.get("limit") or frappe.form_dict.get("limit") or frappe.request.args.get("limit") or 20
	rows = list_inactive_service(search=search, limit=limit)
	return {"status": "success", "data": rows}


@frappe.whitelist(methods=["GET", "POST"])
def list_gift_cards():
	"""
	Admin list of gift cards.

	Request
	-------
	status (optional): Inactive / Active / Used / Expired / Rejected
	search (optional): code / email fragment
	limit, offset (optional)
	"""
	data = get_request_data()
	status = data.get("status") or frappe.form_dict.get("status") or frappe.request.args.get("status")
	search = data.get("search") or frappe.form_dict.get("search") or frappe.request.args.get("search")
	limit = data.get("limit") or frappe.form_dict.get("limit") or frappe.request.args.get("limit") or 50
	offset = data.get("offset") or frappe.form_dict.get("offset") or frappe.request.args.get("offset") or 0
	return list_gift_cards_service(status=status, search=search, limit=limit, offset=offset)
