"""Verify a gift card for a draft Sales Invoice without applying it."""

import frappe

from excel_restaurant_pos.api.coupon.helpers import (
	get_coupon_code_from_request,
	get_request_data,
	get_sales_invoice_name,
)
from excel_restaurant_pos.shared.gift_card.redemption import (
	validate_gift_card_globally,
	verify_gift_card_for_sales_invoice,
)


def _get_gift_card_code_from_request(data: dict) -> str:
	"""Resolve gift card code from request data."""
	coupon_code = (
		data.get("gift_card_code")
		or data.get("coupon_code")
		or frappe.form_dict.get("gift_card_code")
		or frappe.form_dict.get("coupon_code")
	)
	if coupon_code:
		return str(coupon_code).strip()
	return get_coupon_code_from_request(data)


@frappe.whitelist(methods=["POST"])
def verify_gift_card():
	"""
	Validate a gift card without applying it.

	Request
	-------
	sales_invoice (optional): Draft Sales Invoice name
	gift_card_code / coupon_code (required): Gift card code

	When sales_invoice is omitted, only global gift card validity is checked
	(exists, Active, dates, balance). When provided, invoice-specific rules
	(channel, promo conflict, redeemable amount) are included.
	"""
	data = get_request_data()
	sales_invoice = get_sales_invoice_name(data, required=False)
	coupon_code = _get_gift_card_code_from_request(data)

	if sales_invoice:
		return verify_gift_card_for_sales_invoice(sales_invoice, coupon_code)
	return validate_gift_card_globally(coupon_code)
