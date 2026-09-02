"""Gift card line and coupon selection validation."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from excel_restaurant_pos.shared.coupon.services import normalize_coupon_name

GIFT_CARD_TYPE = "Gift Card"
STATUS_INACTIVE = "Inactive"
GIFT_CARD_TYPE_NEW = "New"
GIFT_CARD_TYPE_EXISTING = "Existing"


def invalid_gift_card_message() -> str:
	"""Single wording for a code that is not a usable gift card."""
	return _("The entered code is not a valid Gift Card. Please enter a valid Gift Card code.")


def get_gift_card_lines(doc) -> list:
	"""Return invoice item rows flagged as gift card items."""
	return [item for item in (doc.get("items") or []) if cint(item.get("custom_is_gift_card_item"))]


def resolve_line_gift_amount(line) -> float:
	"""Resolve face value for a gift card line (New or Existing)."""
	gift_type = (line.get("custom_gift_card_type") or "").strip()

	if gift_type == GIFT_CARD_TYPE_EXISTING:
		amount = flt(line.get("custom_gift_amount") or line.get("custom_coupon_value"))
		if amount:
			return amount
		coupon_name = normalize_coupon_name(line.get("custom_gift_card_code"))
		if coupon_name:
			return flt(frappe.db.get_value("Coupon Code", coupon_name, "custom_discount_amount"))
		return 0.0

	# New — prefer line amount, else Item master value (no settings fallback)
	amount = flt(line.get("custom_gift_amount"))
	if amount:
		return amount

	item_code = line.get("item_code")
	if item_code:
		return flt(frappe.db.get_value("Item", item_code, "custom_gift_card_value"))
	return 0.0


def assert_inactive_gift_card(coupon_code: str, *, for_submit: bool = False):
	"""Ensure the coupon is an Inactive Gift Card eligible for sale."""
	coupon_name = normalize_coupon_name(coupon_code)
	if not coupon_name:
		frappe.throw(invalid_gift_card_message(), frappe.DoesNotExistError)

	coupon = frappe.get_doc("Coupon Code", coupon_name)
	if (coupon.coupon_type or "").strip() != GIFT_CARD_TYPE:
		frappe.throw(invalid_gift_card_message())

	status = (coupon.custom_status or "").strip()
	if status != STATUS_INACTIVE:
		frappe.throw(
			_("Gift Card {0} must be Inactive to sell (current status: {1}).").format(
				coupon.name, status or _("blank")
			)
		)

	if coupon.valid_upto and getdate(nowdate()) > getdate(coupon.valid_upto):
		frappe.throw(
			_("Gift Card {0} expired on {1} and cannot be sold.").format(
				coupon.name, coupon.valid_upto
			)
		)

	if for_submit and coupon.custom_generated_on_order:
		frappe.throw(
			_("Gift Card {0} is already linked to Sales Invoice {1}.").format(
				coupon.name, coupon.custom_generated_on_order
			)
		)

	return coupon
