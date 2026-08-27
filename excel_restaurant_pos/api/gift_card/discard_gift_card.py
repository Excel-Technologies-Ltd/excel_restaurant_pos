"""Discard applied gift card(s) from a draft Sales Invoice."""

import frappe

from excel_restaurant_pos.api.coupon.helpers import get_request_data, get_sales_invoice_name
from excel_restaurant_pos.shared.gift_card.redemption import discard_gift_card_from_sales_invoice


@frappe.whitelist(methods=["POST"])
def discard_gift_card():
	"""
	Remove one applied gift card, or all if no code is provided.

	Request
	-------
	sales_invoice (required): Sales Invoice name
	coupon_code / gift_card_code (optional): specific card to remove
	"""
	data = get_request_data()
	sales_invoice = get_sales_invoice_name(data, required=True)
	coupon_code = (
		data.get("gift_card_code")
		or data.get("coupon_code")
		or frappe.form_dict.get("gift_card_code")
		or frappe.form_dict.get("coupon_code")
	)
	result = discard_gift_card_from_sales_invoice(sales_invoice, coupon_code)
	frappe.db.commit()
	return result
