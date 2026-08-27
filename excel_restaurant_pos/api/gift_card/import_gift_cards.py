"""Import Inactive gift cards from CSV."""

import frappe

from excel_restaurant_pos.api.coupon.helpers import get_request_data
from excel_restaurant_pos.shared.gift_card.admin import import_inactive_gift_cards


@frappe.whitelist(methods=["POST"])
def import_gift_cards():
	"""
	Import Inactive gift cards from CSV text.

	Request
	-------
	csv_text or data (required): CSV body

	Headers (optional): code, amount, email
	Without code, codes are auto-generated from ArcPOS Settings prefix.
	"""
	data = get_request_data()
	csv_text = (
		data.get("csv_text")
		or data.get("csv")
		or data.get("content")
		or frappe.form_dict.get("csv_text")
		or frappe.form_dict.get("csv")
		or ""
	)
	if not csv_text:
		frappe.throw("csv_text is required")

	return import_inactive_gift_cards(csv_text)
