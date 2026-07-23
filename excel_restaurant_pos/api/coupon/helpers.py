"""Shared helpers for coupon API endpoints."""

import json

import frappe

from excel_restaurant_pos.shared.coupon.services import get_existing_generated_coupon

COUPON_OVERRIDE_ALIASES = {
    "expire_after_days": ("expire_after_days",),
    "valid_from": ("valid_from",),
    "valid_upto": ("valid_upto",),
    "maximum_use": ("maximum_use", "max_use"),
    "minimum_subtotal": ("minimum_subtotal", "custom_minimum_subtotal"),
    "discount_type": ("discount_type", "custom_discount_type"),
    "discount_amount": ("discount_amount", "discount_rate", "custom_discount_amount"),
    "disc_upto_amount": ("disc_upto_amount", "custom_disc_upto_amount"),
    "redemption_allow_on": (
        "redemption_allow_on",
        "custom_redeemption_allow_on",
        "cc_allow_on_redeem",
    ),
    "linked_email": ("linked_email", "custom_linked_email", "coupon_for"),
    "coupon_type": ("coupon_type",),
    "pricing_rule": ("pricing_rule", "default_pricing_rule"),
    "description": ("description",),
    "coupon_code_prefix": ("coupon_code_prefix",),
}


def get_request_data() -> dict:
    """Parse request payload from form fields or JSON body."""
    raw_data = frappe.form_dict.get("data")
    if raw_data:
        if isinstance(raw_data, str):
            return json.loads(raw_data)
        return raw_data

    return dict(frappe.form_dict)


def get_coupon_code_from_request(data: dict | None = None) -> str:
    """Resolve coupon code from request data."""
    payload = data or get_request_data()
    coupon_code = (
        payload.get("coupon_code")
        or payload.get("custom_coupon_code")
        or frappe.form_dict.get("coupon_code")
        or frappe.form_dict.get("custom_coupon_code")
        or frappe.request.args.get("coupon_code")
    )
    if not coupon_code:
        frappe.throw("coupon_code is required", frappe.MandatoryError)
    return coupon_code.strip()


def get_sales_invoice_name(data: dict | None = None, required: bool = True) -> str | None:
    """Resolve the Sales Invoice name from request data."""
    payload = data or get_request_data()
    sales_invoice = (
        payload.get("sales_invoice")
        or payload.get("invoice_name")
        or payload.get("docname")
        or frappe.form_dict.get("sales_invoice")
        or frappe.form_dict.get("invoice_name")
        or frappe.form_dict.get("docname")
        or frappe.request.args.get("sales_invoice")
        or frappe.request.args.get("invoice_name")
    )
    if not sales_invoice:
        if required:
            frappe.throw("sales_invoice is required", frappe.MandatoryError)
        return None

    if not frappe.db.exists("Sales Invoice", sales_invoice):
        frappe.throw(f"Sales Invoice {sales_invoice} does not exist", frappe.DoesNotExistError)

    return sales_invoice


def parse_coupon_overrides(data: dict | None) -> dict:
    """Extract optional coupon field overrides from API request data."""
    overrides = {}
    if not data:
        return overrides

    for field, aliases in COUPON_OVERRIDE_ALIASES.items():
        for alias in aliases:
            if alias not in data:
                continue
            value = data.get(alias)
            if value is None or value == "":
                continue
            overrides[field] = value
            break

    return overrides


def format_coupon_response(coupon_name: str, generated: bool = False) -> dict:
    """Return a normalized coupon payload for API consumers."""
    coupon = frappe.get_doc("Coupon Code", coupon_name)
    return {
        "status": "success",
        "generated": generated,
        "coupon_code": coupon.coupon_code,
        "coupon_name": coupon.coupon_name,
        "coupon_status": coupon.custom_status,
        "discount_type": coupon.custom_discount_type,
        "discount_amount": coupon.custom_discount_amount,
        "disc_upto_amount": coupon.custom_disc_upto_amount,
        "valid_from": coupon.valid_from,
        "valid_upto": coupon.valid_upto,
        "linked_email": coupon.custom_linked_email,
        "generated_on_order": coupon.custom_generated_on_order,
        "redeemed_on_order": coupon.custom_redeemed_on_order,
        "maximum_use": coupon.maximum_use,
        "used": coupon.used,
        "minimum_subtotal": coupon.custom_minimum_subtotal,
        "redemption_allow_on": coupon.custom_redeemption_allow_on,
        "qr_code": coupon.custom_qr_code,
        "barcode": coupon.custom_barcode,
    }


def get_generated_coupon_for_invoice(sales_invoice: str) -> dict | None:
    """Return the coupon already generated for an invoice, if any."""
    doc = frappe.get_doc("Sales Invoice", sales_invoice)
    existing_coupon = get_existing_generated_coupon(doc)
    if not existing_coupon:
        return None

    return format_coupon_response(existing_coupon.name, generated=False)
