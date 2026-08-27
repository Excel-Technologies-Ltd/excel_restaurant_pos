"""Apply one or more gift cards to a draft Sales Invoice."""

import frappe

from excel_restaurant_pos.api.coupon.helpers import (
	get_coupon_code_from_request,
	get_request_data,
	get_sales_invoice_name,
)
from excel_restaurant_pos.shared.gift_card.redemption import (
	apply_gift_cards_to_sales_invoice,
	parse_gift_card_codes,
)


@frappe.whitelist(methods=["POST"])
def apply_gift_card():
	"""
	Validate and apply gift card(s) to a draft Sales Invoice.

	Request
	-------
	sales_invoice (required): Sales Invoice name
	gift_card_code / coupon_code (optional): one code, or comma/newline-separated list
	gift_card_codes / coupon_codes (optional): JSON array of codes

	Notes
	-----
	- Codes are applied **in order** (first → last).
	- Each code takes remaining due after previous cards.
	- When the invoice is fully covered, remaining codes are skipped.
	- Cannot combine with a promotional coupon.
	- Balance is reduced only when the invoice is submitted.
	"""
	data = get_request_data()
	sales_invoice = get_sales_invoice_name(data, required=True)

	codes = parse_gift_card_codes(
		data.get("gift_card_codes"),
		data.get("coupon_codes"),
		data.get("gift_card_code"),
		data.get("coupon_code"),
		frappe.form_dict.get("gift_card_codes"),
		frappe.form_dict.get("coupon_codes"),
		frappe.form_dict.get("gift_card_code"),
		frappe.form_dict.get("coupon_code"),
	)
	if not codes:
		# Fall back to shared helper (same keys as promo APIs)
		single = get_coupon_code_from_request(data)
		codes = parse_gift_card_codes(single)

	result = apply_gift_cards_to_sales_invoice(sales_invoice, codes)
	frappe.db.commit()
	return result
