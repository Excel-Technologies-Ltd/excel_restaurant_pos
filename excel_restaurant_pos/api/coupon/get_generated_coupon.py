"""Fetch generated coupon for a Sales Invoice."""

import frappe

from .helpers import get_generated_coupon_for_invoice, get_sales_invoice_name


@frappe.whitelist(methods=["GET"])
def get_generated_coupon():
    """
    Return the coupon generated for a Sales Invoice, if one exists.

    Request
    -------
    sales_invoice (required): Sales Invoice name
    """
    sales_invoice = get_sales_invoice_name()
    coupon = get_generated_coupon_for_invoice(sales_invoice)
    if not coupon:
        return {"status": "not_found", "coupon_code": None}

    return coupon
