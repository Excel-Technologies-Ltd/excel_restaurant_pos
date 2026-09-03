"""Mirror a Sales Invoice's docstatus onto the coupons generated on it.

`Coupon Code.custom_generated_on_order` links a coupon back to the invoice that
produced it. That invoice can still be submitted or cancelled afterwards, and a
coupon from a voided order must not stay spendable, so `custom_order_status`
tracks the invoice docstatus and a cancellation also rejects the coupon.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from excel_restaurant_pos.shared.coupon.services import COUPON_STATUS_REJECTED

COUPON_DOCTYPE = "Coupon Code"
LINK_FIELD = "custom_generated_on_order"

# Mirrors frappe's docstatus, which is what the field records.
ORDER_STATUS_DRAFT = 0
ORDER_STATUS_SUBMITTED = 1
ORDER_STATUS_CANCELLED = 2


def get_coupons_generated_on(invoice_name: str) -> list:
	"""Coupon names generated on one Sales Invoice."""
	if not invoice_name:
		return []
	return frappe.get_all(
		COUPON_DOCTYPE, filters={LINK_FIELD: invoice_name}, pluck="name"
	)


def apply_coupon_order_status(coupon_name: str, order_status: int, reject: bool = False) -> bool:
	"""Write the status pair, skipping coupons that already match.

	Written with db.set_value rather than a full save: the Coupon Code on_update
	hook regenerates codes, barcodes and QR images, which has nothing to do with
	the order status and would run on every invoice submit.
	"""
	current = frappe.db.get_value(
		COUPON_DOCTYPE, coupon_name, ["custom_order_status", "custom_status"], as_dict=True
	)
	if not current:
		return False

	values = {}
	if cint(current.custom_order_status) != order_status:
		values["custom_order_status"] = order_status
	if reject and current.custom_status != COUPON_STATUS_REJECTED:
		values["custom_status"] = COUPON_STATUS_REJECTED

	if not values:
		return False

	frappe.db.set_value(COUPON_DOCTYPE, coupon_name, values)
	return True


def sync_coupon_order_status(invoice, order_status: int, reject: bool = False) -> int:
	"""Push `order_status` onto every coupon generated on this invoice."""
	invoice_name = invoice if isinstance(invoice, str) else invoice.name

	updated = 0
	for coupon_name in get_coupons_generated_on(invoice_name):
		if apply_coupon_order_status(coupon_name, order_status, reject):
			updated += 1

	return updated


def on_submit_sales_invoice_coupon_status(doc, method=None):
	"""Invoice submitted: the coupons it generated are now backed by a real order."""
	sync_coupon_order_status(doc, ORDER_STATUS_SUBMITTED)


def on_cancel_sales_invoice_coupon_status(doc, method=None):
	"""Invoice cancelled: reject the coupons it generated so they cannot be spent.

	Rejected is terminal in `refresh_coupon_status`, so neither the nightly expiry
	pass nor a later validation can quietly make one redeemable again.
	"""
	sync_coupon_order_status(doc, ORDER_STATUS_CANCELLED, reject=True)
