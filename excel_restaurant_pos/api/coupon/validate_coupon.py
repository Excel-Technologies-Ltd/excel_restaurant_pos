"""Validate a coupon globally without a Sales Invoice."""

import frappe

from excel_restaurant_pos.shared.coupon.services import validate_coupon_globally

from .helpers import get_coupon_code_from_request, get_request_data


@frappe.whitelist(methods=["POST"], allow_guest=True)
def validate_coupon():
    """
    Validate a coupon without Sales Invoice context.

    Request
    -------
    coupon_code (required): Coupon code to validate

    Checks
    ------
    - Coupon exists
    - Status is Active
    - Validity dates
    - Usage limit

    Does not check order channel or minimum subtotal (invoice-specific rules).
    Use api.coupons.verify when validating against a draft Sales Invoice.
    """
    data = get_request_data()
    coupon_code = get_coupon_code_from_request(data)
    return validate_coupon_globally(coupon_code)
