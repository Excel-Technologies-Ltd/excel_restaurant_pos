"""Manual coupon generation API."""

import frappe

from excel_restaurant_pos.shared.coupon.services import (
    generate_coupon_for_sales_invoice,
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
    Manually generate a coupon for a Sales Invoice.

    Request
    -------
    sales_invoice (required): Sales Invoice name
    data (optional): JSON string/object with generation overrides

    Optional overrides
    ------------------
    expire_after_days, valid_from, valid_upto, maximum_use, max_use,
    minimum_subtotal, discount_type, discount_amount, discount_rate,
    redemption_allow_on, linked_email, coupon_for, coupon_type,
    pricing_rule, description, coupon_code_prefix

    Rules
    -----
    - Manual generation is allowed only when auto-generate is disabled.
    - One generated coupon per invoice.
    - Idempotent: returns the existing coupon if already generated.
    - Unspecified fields fall back to ArcPOS Settings defaults.
    """
    data = get_request_data()
    sales_invoice = get_sales_invoice_name(data)
    overrides = parse_coupon_overrides(data)

    doc = frappe.get_doc("Sales Invoice", sales_invoice)
    existing_coupon = get_existing_generated_coupon(doc)
    if existing_coupon:
        frappe.db.commit()
        return format_coupon_response(existing_coupon.name, generated=False)

    coupon_code = generate_coupon_for_sales_invoice(sales_invoice, overrides=overrides)
    frappe.db.commit()
    return format_coupon_response(coupon_code, generated=True)
