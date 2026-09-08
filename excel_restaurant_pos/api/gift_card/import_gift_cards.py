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

	Headers (optional): code, amount, email, expiry, validity_days
	Without code, codes are auto-generated from ArcPOS Settings prefix.

	validity_days (optional): days from the sale, applied to rows without their
		own. Prefer this over an absolute expiry for stock printed in advance.
	valid_upto / expiry_date (optional): absolute expiry applied to rows without
		their own. validity_days wins when a card carries both.
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

	valid_upto = (
		data.get("valid_upto")
		or data.get("expiry_date")
		or data.get("expiry")
		or frappe.form_dict.get("valid_upto")
		or frappe.form_dict.get("expiry_date")
	)
	validity_days = (
		data.get("validity_days")
		or data.get("validity")
		or frappe.form_dict.get("validity_days")
	)

	return import_inactive_gift_cards(
		csv_text, valid_upto=valid_upto, validity_days=validity_days
	)
