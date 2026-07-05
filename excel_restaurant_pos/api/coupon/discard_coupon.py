"""Discard an applied coupon from a draft Sales Invoice."""

import frappe

from excel_restaurant_pos.shared.coupon.services import discard_coupon_from_sales_invoice

from .helpers import get_request_data, get_sales_invoice_name


@frappe.whitelist(methods=["POST"])
def discard_coupon():
    """
    Remove the applied coupon and its discount from a draft Sales Invoice.

    Request
    -------
    sales_invoice (required): Sales Invoice name
    """
    data = get_request_data()
    sales_invoice = get_sales_invoice_name(data, required=True)
    result = discard_coupon_from_sales_invoice(sales_invoice)
    frappe.db.commit()
    return result
