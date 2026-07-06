"""Manual coupon generation API."""

import frappe

from excel_restaurant_pos.shared.coupon.services import (
    generate_manual_coupon,
    get_existing_generated_coupon,
)

from .helpers import (
    format_coupon_response,
    get_request_data,
    get_sales_invoice_name,
    parse_coupon_overrides,
)


@frappe.whitelist(methods=["POST"])
def generate_coupon():
    """
    Manually generate a coupon, with or without a Sales Invoice.

    Request
    -------
    sales_invoice (optional): Sales Invoice name to link the coupon to
    data (optional): JSON string/object with generation overrides

    Optional overrides
    ------------------
    expire_after_days, valid_from, valid_upto, maximum_use, max_use,
    minimum_subtotal, discount_type, discount_amount, discount_rate,
    redemption_allow_on, linked_email, coupon_for, coupon_type,
    pricing_rule, description, coupon_code_prefix

    Rules
    -----
    - Manual generation requires Allow Manual Generate in ArcPOS Settings.
    - When sales_invoice is provided: one generated coupon per invoice (idempotent).
    - When sales_invoice is omitted: creates a standalone coupon.
    - Unspecified fields fall back to ArcPOS Settings defaults.
    """
    data = get_request_data()
    sales_invoice = get_sales_invoice_name(data, required=False)
    overrides = parse_coupon_overrides(data)

    if sales_invoice:
        doc = frappe.get_doc("Sales Invoice", sales_invoice)
        existing_coupon = get_existing_generated_coupon(doc)
        if existing_coupon:
            frappe.db.commit()
            return format_coupon_response(existing_coupon.name, generated=False)

    coupon_code = generate_manual_coupon(overrides=overrides, sales_invoice=sales_invoice)
    frappe.db.commit()
    return format_coupon_response(coupon_code, generated=True)
