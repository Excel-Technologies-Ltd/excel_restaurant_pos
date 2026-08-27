"""Apply a gift card to a draft Sales Invoice."""

import frappe

from excel_restaurant_pos.api.coupon.helpers import (
	get_coupon_code_from_request,
	get_request_data,
	get_sales_invoice_name,
)
from excel_restaurant_pos.shared.gift_card.redemption import apply_gift_card_to_sales_invoice


@frappe.whitelist(methods=["POST"])
def apply_gift_card():
	"""
	Validate and apply a gift card to a draft Sales Invoice.

	Request
	-------
	sales_invoice (required): Sales Invoice name
	coupon_code / gift_card_code (required): Gift card code

	Notes
	-----
	- Multiple gift cards may be applied; each takes remaining due.
	- Cannot combine with a promotional coupon.
	- Balance is reduced only when the invoice is submitted.
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
	result = apply_gift_card_to_sales_invoice(sales_invoice, coupon_code)
	frappe.db.commit()
	return result
