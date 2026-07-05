"""Verify a coupon for a draft Sales Invoice without applying it."""

import frappe

from excel_restaurant_pos.shared.coupon.services import verify_coupon_for_sales_invoice

from .helpers import get_coupon_code_from_request, get_request_data, get_sales_invoice_name


@frappe.whitelist(methods=["POST"])
def verify_coupon():
    """
    Validate a coupon for a draft Sales Invoice without applying it.

    Request
    -------
    sales_invoice (required): Sales Invoice name
    coupon_code (required): Coupon code to validate
    """
    data = get_request_data()
    sales_invoice = get_sales_invoice_name(data, required=True)
    coupon_code = get_coupon_code_from_request(data)
    return verify_coupon_for_sales_invoice(sales_invoice, coupon_code)
