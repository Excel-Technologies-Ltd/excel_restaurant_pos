"""Verify and apply a coupon to a draft Sales Invoice."""

import frappe

from excel_restaurant_pos.shared.coupon.services import apply_coupon_to_sales_invoice

from .helpers import get_coupon_code_from_request, get_request_data, get_sales_invoice_name


@frappe.whitelist(methods=["POST"])
def apply_coupon():
    """
    Validate and apply a coupon to a draft Sales Invoice.

    Request
    -------
    sales_invoice (required): Sales Invoice name
    coupon_code (required): Coupon code to apply

    Notes
    -----
    - Replaces any previously applied coupon and recalculates discount/totals.
    - Coupon usage (`used`) is incremented only when the invoice is submitted.
    """
    data = get_request_data()
    sales_invoice = get_sales_invoice_name(data, required=True)
    coupon_code = get_coupon_code_from_request(data)
    result = apply_coupon_to_sales_invoice(sales_invoice, coupon_code)
    frappe.db.commit()
    return result
