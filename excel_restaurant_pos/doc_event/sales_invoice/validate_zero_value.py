"""Reject zero-value Sales Invoices unless a coupon or gift card reduced the total to zero."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from excel_restaurant_pos.shared.coupon.services import resolve_applied_coupon_code
from excel_restaurant_pos.shared.gift_card.redemption import invoice_has_applied_gift_cards


def _discount_reduced_positive_subtotal_to_zero(doc) -> bool:
    """True when a promo coupon or applied gift card reduced a positive subtotal."""
    if flt(doc.get("total")) <= 0 or flt(doc.get("discount_amount")) <= 0:
        return False

    if resolve_applied_coupon_code(doc):
        return True

    return invoice_has_applied_gift_cards(doc)


def validate_non_zero_grand_total(doc, method: str = None):
    """Block a zero (or negative) Grand Total unless a valid discount caused it.

    Runs on validate, so it guards every creation and submission path (POS, Web,
    Mobile, and the APIs all reach here through doc.save()/submit()). A zero total
    is allowed only when a redeemed promo coupon or gift card reduced a positive
    order down to zero. Any other zero (free/zero-priced items, or a manual price/
    discount edit with no coupon/gift card) is rejected. Credit notes / returns are
    naturally zero-or-negative and are exempt.
    """
    if cint(doc.get("is_return")):
        return

    if flt(doc.get("grand_total")) > 0:
        return

    if _discount_reduced_positive_subtotal_to_zero(doc):
        return

    frappe.throw(
        _(
            "Grand Total cannot be zero. A zero-value invoice is only allowed when a "
            "valid coupon or gift card reduces the total to zero."
        ),
        title=_("Zero-Value Invoice"),
    )
