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
from excel_restaurant_pos.utils import rate_limit_by_caller

# Applying is a code oracle in the same way verifying is -- an invalid code
# throws and a valid one succeeds -- so a public caller gets a budget.
APPLY_RATE_LIMIT = 20
APPLY_RATE_WINDOW = 60


@frappe.whitelist(methods=["POST"], allow_guest=True)
def apply_gift_card():
	"""
	Validate and apply gift card(s) to a draft Sales Invoice.

	Public, so a website customer can pay with a gift card without signing in.
	The invoice must still be a draft, which is the same rule the already public
	invoice APIs follow, and no balance moves here -- it is reduced on submit.
	Throttled per caller (per IP for guests).

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
	rate_limit_by_caller(
		"gift_card_apply", limit=APPLY_RATE_LIMIT, seconds=APPLY_RATE_WINDOW
	)

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
