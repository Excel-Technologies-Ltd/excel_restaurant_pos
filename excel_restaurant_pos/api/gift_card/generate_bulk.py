"""Bulk-create Inactive gift cards."""

import frappe

from excel_restaurant_pos.api.coupon.helpers import get_request_data
from excel_restaurant_pos.shared.gift_card.admin import generate_bulk_inactive_gift_cards


@frappe.whitelist(methods=["POST"])
def generate_bulk_gift_cards():
	"""
	Create N Inactive gift cards.

	Request
	-------
	qty (required): number of cards (1–500)
	amount (required): face value
	prefix (optional): override ArcPOS Settings gift_card_prefix
	linked_email (optional): email stamped on each card
	valid_upto / expiry_date (optional): expiry stamped on each card. Kept when the
		card is sold; without it activation falls back to the ArcPOS Settings expiry.
	"""
	data = get_request_data()
	qty = data.get("qty") or frappe.form_dict.get("qty")
	amount = data.get("amount") or frappe.form_dict.get("amount")
	prefix = data.get("prefix") or frappe.form_dict.get("prefix")
	linked_email = data.get("linked_email") or frappe.form_dict.get("linked_email")
	valid_upto = (
		data.get("valid_upto")
		or data.get("expiry_date")
		or data.get("expiry")
		or frappe.form_dict.get("valid_upto")
		or frappe.form_dict.get("expiry_date")
	)

	if qty is None or amount is None:
		frappe.throw("qty and amount are required")

	return generate_bulk_inactive_gift_cards(
		qty=qty,
		amount=amount,
		prefix=prefix,
		linked_email=linked_email,
		valid_upto=valid_upto,
	)
