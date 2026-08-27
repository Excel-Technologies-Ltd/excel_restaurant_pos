"""Verify a gift card for a draft Sales Invoice without applying it."""

import frappe

from excel_restaurant_pos.api.coupon.helpers import (
	get_coupon_code_from_request,
	get_request_data,
	get_sales_invoice_name,
)
from excel_restaurant_pos.shared.gift_card.redemption import verify_gift_card_for_sales_invoice


@frappe.whitelist(methods=["POST"])
def verify_gift_card():
	"""
	Validate a gift card for a draft Sales Invoice without applying it.

	Request
	-------
	sales_invoice (required): Sales Invoice name
	coupon_code / gift_card_code (required): Gift card code
	"""
	data = get_request_data()
	sales_invoice = get_sales_invoice_name(data, required=True)
	coupon_code = (
		data.get("gift_card_code")
		or data.get("coupon_code")
		or frappe.form_dict.get("gift_card_code")
	)
	if not coupon_code:
		coupon_code = get_coupon_code_from_request(data)
	return verify_gift_card_for_sales_invoice(sales_invoice, coupon_code)
