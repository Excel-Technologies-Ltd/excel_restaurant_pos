"""Reject zero-value Sales Invoices unless a coupon reduced the total to zero."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from excel_restaurant_pos.shared.coupon.services import resolve_applied_coupon_code


def validate_non_zero_grand_total(doc, method: str = None):
    """Block a zero (or negative) Grand Total unless a valid coupon caused it.

    Runs on validate, so it guards every creation and submission path (POS, Web,
    Mobile, and the APIs all reach here through doc.save()/submit()). A zero total
    is allowed only when a redeemed coupon reduced a positive order down to zero --
    a 100%-off or a flat coupon that covers the whole subtotal. Any other zero
    (free/zero-priced items, or a manual price/discount edit with no coupon) is
    rejected. Credit notes / returns are naturally zero-or-negative and are exempt.
    """
    if cint(doc.get("is_return")):
        return

    if flt(doc.get("grand_total")) > 0:
        return

    # Grand Total is zero (or below). Allow only when a redeemed coupon reduced a
    # positive subtotal to zero -- i.e. the coupon is what made it free.
    coupon_reduced_to_zero = (
        bool(resolve_applied_coupon_code(doc))
        and flt(doc.get("total")) > 0
        and flt(doc.get("discount_amount")) > 0
    )
    if coupon_reduced_to_zero:
        return

    frappe.throw(
        _(
            "Grand Total cannot be zero. A zero-value invoice is only allowed when a "
            "valid coupon reduces the total to zero."
        ),
        title=_("Zero-Value Invoice"),
    )
