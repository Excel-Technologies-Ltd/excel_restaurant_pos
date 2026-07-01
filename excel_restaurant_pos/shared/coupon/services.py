"""Coupon generation, validation, and redemption helpers."""

from __future__ import annotations

import random
import re
import string
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from excel_restaurant_pos.shared.contacts.get_customer_emails import get_customer_emails


COUPON_STATUS_ACTIVE = "Active"
COUPON_STATUS_EXPIRED = "Expired"
COUPON_STATUS_USED = "Used"
COUPON_GENERATION_RETRY_LIMIT = 50
COUPON_RANDOM_CHARS = string.ascii_uppercase + string.digits


def get_coupon_settings():
    """Return ArcPOS coupon settings if configured."""
    if not frappe.db.exists("ArcPOS Settings", "ArcPOS Settings"):
        return None

    return frappe.get_cached_doc("ArcPOS Settings", "ArcPOS Settings")


def validate_coupon_generation_settings(settings, overrides=None):
    """Ensure ArcPOS coupon settings required by Coupon Code exist."""
    overrides = overrides or {}

    if not settings:
        frappe.throw(_("ArcPOS Settings is required before generating coupon codes."))

    coupon_type = overrides.get("coupon_type") or settings.coupon_type
    if not coupon_type:
        frappe.throw(
            _("Please set Coupon Type in ArcPOS Settings before generating coupon codes."),
            frappe.MandatoryError,
        )

    pricing_rule = (overrides.get("pricing_rule") or settings.default_pricing_rule or "").strip()
    if not pricing_rule:
        frappe.throw(
            _(
                "Please set Default Pricing Rule in ArcPOS Settings before generating coupon codes."
            ),
            frappe.MandatoryError,
        )

    if not frappe.db.exists("Pricing Rule", pricing_rule):
        frappe.throw(
            _("Default Pricing Rule {0} does not exist. Please update ArcPOS Settings.").format(
                pricing_rule
            ),
            frappe.DoesNotExistError,
        )

    return {"coupon_type": coupon_type, "pricing_rule": pricing_rule}


def calculate_invoice_subtotal(doc) -> float:
    """Return the invoice subtotal before tax and discounts."""
    subtotal = 0.0
    for item in doc.get("items") or []:
        price_list_rate = flt(item.get("price_list_rate"))
        qty = flt(item.get("qty"))
        subtotal += price_list_rate * qty if price_list_rate else flt(item.get("amount"))

    if subtotal:
        return subtotal

    return flt(doc.get("total") or doc.get("net_total") or 0)


def is_online_order(doc) -> bool:
    return (doc.get("custom_order_from") or "").strip().lower() == "website"


def normalize_channel(order_from: str | None, service_type: str | None) -> tuple[str, str]:
    return (order_from or "").strip().lower(), (service_type or "").strip().lower()


def is_channel_allowed(order_from: str | None, service_type: str | None, allowed_on: str | None) -> bool:
    """Check whether an order channel matches the configured coupon channel."""
    order_from_value, service_type_value = normalize_channel(order_from, service_type)
    allowed_on_value = (allowed_on or "").strip()

    pos_pairs = {
        ("table", "dine-in"),
        ("table", "takeout"),
        ("in store", "pickup"),
        ("in store", "delivery"),
    }
    online_pickup_pair = ("website", "pickup")
    online_delivery_pair = ("website", "delivery")
    all_pairs = pos_pairs | {online_pickup_pair, online_delivery_pair}
    current_pair = (order_from_value, service_type_value)

    if allowed_on_value == "POS":
        return current_pair in pos_pairs
    if allowed_on_value == "Online Pickup":
        return current_pair == online_pickup_pair
    if allowed_on_value == "Online Delivery":
        return current_pair == online_delivery_pair
    if allowed_on_value == "Only Online":
        return current_pair in {online_pickup_pair, online_delivery_pair}
    if allowed_on_value == "All":
        return current_pair in all_pairs

    return False


def resolve_validity_dates(settings, overrides=None) -> tuple[Any, Any]:
    """Resolve valid_from and valid_upto from overrides or ArcPOS settings."""
    overrides = overrides or {}

    if overrides.get("valid_upto"):
        valid_from = getdate(overrides.get("valid_from") or nowdate())
        valid_upto = getdate(overrides["valid_upto"])
        if valid_upto < valid_from:
            frappe.throw(_("Valid Upto must be on or after Valid From."))
        return valid_from, valid_upto

    expire_after_days = overrides.get("expire_after_days")
    if expire_after_days in (None, ""):
        expire_after_days = settings.expire_after_days

    expire_after = cint(expire_after_days or 0)
    if not expire_after:
        frappe.throw(
            _(
                "Expire After (Days) is required. Set it in ArcPOS Settings or pass expire_after_days / valid_upto."
            ),
            frappe.MandatoryError,
        )

    valid_from = getdate(overrides.get("valid_from") or nowdate())
    valid_upto = add_days(valid_from, expire_after)
    return valid_from, valid_upto


def calculate_validity_dates(expire_after_days: Any) -> tuple[str, str | None]:
    """Return valid_from and valid_upto strings."""
    valid_from = nowdate()
    expire_after = cint(expire_after_days or 0)
    valid_upto = add_days(valid_from, expire_after) if expire_after else None
    return valid_from, valid_upto


def get_coupon_linked_email(doc, overrides=None) -> str:
    """Resolve the coupon's linked email using the requested priority."""
    overrides = overrides or {}
    override_email = (overrides.get("linked_email") or "").strip()
    if override_email:
        return override_email

    invoice_coupon_for = (doc.get("custom_coupon_for") or "").strip()
    if invoice_coupon_for:
        return invoice_coupon_for

    customer = doc.get("customer")
    if customer:
        for email in get_customer_emails(customer):
            if cint(email.get("is_primary")):
                return email.get("email_id") or ""
        customer_email = frappe.db.get_value("Customer", customer, "email_id")
        if customer_email:
            return customer_email

    return (doc.get("custom_email_address") or "").strip()


def build_coupon_code(template: str) -> str:
    """Create a coupon code by replacing # with random chars."""
    raw_template = template or "SAVE####"
    replaced = "".join(
        random.choice(COUPON_RANDOM_CHARS) if char == "#" else char for char in raw_template
    )
    sanitized = re.sub(r"[^A-Za-z0-9]", "", replaced).upper()
    return sanitized or "".join(random.choice(COUPON_RANDOM_CHARS) for _ in range(8))


def generate_unique_coupon_code(template: str) -> str:
    """Generate a globally unique coupon code."""
    for _ in range(COUPON_GENERATION_RETRY_LIMIT):
        coupon_code = build_coupon_code(template)
        if not frappe.db.exists("Coupon Code", {"name": coupon_code}) and not frappe.db.exists(
            "Coupon Code", {"coupon_code": coupon_code}
        ):
            return coupon_code

    frappe.throw(_("Unable to generate a unique coupon code. Please try again."))


def refresh_coupon_status(coupon_doc_or_name, save: bool = True) -> str:
    """Refresh the coupon status based on validity and usage."""
    coupon = (
        frappe.get_doc("Coupon Code", coupon_doc_or_name)
        if isinstance(coupon_doc_or_name, str)
        else coupon_doc_or_name
    )

    today = getdate(nowdate())
    valid_upto = getdate(coupon.valid_upto) if coupon.valid_upto else None
    maximum_use = flt(coupon.maximum_use) if coupon.maximum_use is not None else None
    used = flt(coupon.used)

    status = COUPON_STATUS_ACTIVE
    if valid_upto and today > valid_upto:
        status = COUPON_STATUS_EXPIRED
    elif maximum_use not in (None, 0) and used >= maximum_use:
        status = COUPON_STATUS_USED

    if coupon.custom_status != status:
        coupon.custom_status = status
        if save:
            coupon.save(ignore_permissions=True)

    return status


def expire_due_coupon_codes() -> int:
    """Mark active coupons as expired once valid_upto has passed."""
    today = nowdate()
    coupon_names = frappe.db.sql(
        """
        SELECT name
        FROM `tabCoupon Code`
        WHERE valid_upto IS NOT NULL
          AND valid_upto < %s
          AND IFNULL(custom_status, %s) = %s
        """,
        (today, COUPON_STATUS_ACTIVE, COUPON_STATUS_ACTIVE),
        pluck=True,
    )

    expired_count = 0
    for coupon_name in coupon_names:
        status = refresh_coupon_status(coupon_name, save=True)
        if status == COUPON_STATUS_EXPIRED:
            expired_count += 1

    if expired_count:
        frappe.db.commit()
        frappe.logger("coupon").info(f"Marked {expired_count} coupon codes as expired")

    return expired_count


def get_existing_generated_coupon(doc):
    """Return an existing coupon generated for the given invoice, if any."""
    coupon_name = (doc.get("custom_generated_coupon_code") or doc.get("custom_coupon_code") or "").strip()
    if coupon_name and frappe.db.exists("Coupon Code", coupon_name):
        coupon = frappe.get_doc("Coupon Code", coupon_name)
        if not coupon.custom_generated_on_order or coupon.custom_generated_on_order == doc.name:
            return coupon

    generated_coupon_name = frappe.db.get_value(
        "Coupon Code", {"custom_generated_on_order": doc.name}, "name"
    )
    if generated_coupon_name:
        return frappe.get_doc("Coupon Code", generated_coupon_name)

    return None


def has_non_generated_coupon_on_invoice(doc) -> bool:
    """Return True when the invoice already carries a different applied coupon."""
    coupon_code = (doc.get("custom_coupon_code") or "").strip()
    if not coupon_code:
        return False

    existing_generated_coupon = get_existing_generated_coupon(doc)
    if existing_generated_coupon and existing_generated_coupon.name == coupon_code:
        return False

    return True


def is_generation_allowed(doc, settings) -> bool:
    """Check whether the invoice is eligible for coupon generation."""
    if not settings or not cint(settings.allow_auto_generate_cc):
        return False
    if not is_channel_allowed(
        doc.get("custom_order_from"), doc.get("custom_service_type"), settings.auto_generate_on
    ):
        return False
    minimum_subtotal = flt(settings.minimum_subtotal_generate)
    if minimum_subtotal and calculate_invoice_subtotal(doc) < minimum_subtotal:
        return False
    if has_non_generated_coupon_on_invoice(doc):
        return False
    return not bool(get_existing_generated_coupon(doc))


def build_coupon_values(doc, settings, overrides=None) -> dict:
    """Build Coupon Code field values from settings with optional overrides."""
    overrides = overrides or {}
    validated = validate_coupon_generation_settings(settings, overrides)
    valid_from, valid_upto = resolve_validity_dates(settings, overrides)

    minimum_subtotal = overrides.get("minimum_subtotal")
    if minimum_subtotal in (None, ""):
        minimum_subtotal = settings.minimum_subtotal_redeem
    custom_minimum_subtotal = flt(minimum_subtotal) if minimum_subtotal not in (None, "") else None

    maximum_use = overrides.get("maximum_use")
    if maximum_use in (None, ""):
        maximum_use = settings.max_use
    maximum_use = cint(maximum_use) if maximum_use not in (None, "") else None

    discount_type = overrides.get("discount_type") or settings.discount_type
    discount_amount = overrides.get("discount_amount")
    if discount_amount in (None, ""):
        discount_amount = settings.discount_rate

    redemption_allow_on = overrides.get("redemption_allow_on") or settings.cc_allow_on_redeem

    return {
        "coupon_type": validated["coupon_type"],
        "pricing_rule": validated["pricing_rule"],
        "description": overrides.get("description") or "",
        "valid_from": valid_from,
        "valid_upto": valid_upto,
        "maximum_use": maximum_use,
        "custom_discount_type": discount_type,
        "custom_discount_amount": flt(discount_amount) if discount_amount not in (None, "") else None,
        "custom_minimum_subtotal": custom_minimum_subtotal,
        "custom_redeemption_allow_on": redemption_allow_on,
        "custom_linked_email": get_coupon_linked_email(doc, overrides),
        "coupon_code_prefix": overrides.get("coupon_code_prefix") or settings.coupon_code_prefix,
    }


def create_coupon_doc(doc, settings, overrides=None, defer_invoice_link=False):
    """Create and insert a Coupon Code document from ArcPOS Settings."""
    overrides = overrides or {}
    coupon_values = build_coupon_values(doc, settings, overrides)
    coupon_code = generate_unique_coupon_code(coupon_values["coupon_code_prefix"])

    coupon_fields = {
        "doctype": "Coupon Code",
        "name": coupon_code,
        "coupon_name": coupon_code,
        "coupon_code": coupon_code,
        "coupon_type": coupon_values["coupon_type"],
        "pricing_rule": coupon_values["pricing_rule"],
        "description": coupon_values["description"],
        "valid_from": coupon_values["valid_from"],
        "valid_upto": coupon_values["valid_upto"],
        "maximum_use": coupon_values["maximum_use"],
        "used": 0,
        "custom_discount_type": coupon_values["custom_discount_type"],
        "custom_discount_amount": coupon_values["custom_discount_amount"],
        "custom_created_on": getdate(now_datetime()),
        "custom_linked_email": coupon_values["custom_linked_email"],
        "custom_status": COUPON_STATUS_ACTIVE,
        "custom_minimum_subtotal": coupon_values["custom_minimum_subtotal"],
        "custom_redeemption_allow_on": coupon_values["custom_redeemption_allow_on"],
        "custom_redeemed_on_order": None,
    }

    # Defer invoice link during one-step submit to avoid LinkValidationError.
    if not defer_invoice_link and doc.name:
        coupon_fields["custom_generated_on_order"] = doc.name

    coupon_doc = frappe.get_doc(coupon_fields)
    coupon_doc.insert(ignore_permissions=True)
    return coupon_doc


def link_coupon_to_invoice(doc, coupon_code: str):
    """Attach the generated coupon to the invoice in-memory."""
    doc.custom_coupon_code = coupon_code
    doc.custom_generated_coupon_code = coupon_code


def persist_coupon_links_to_invoice(docname: str, coupon_code: str):
    """Persist coupon links directly for submitted/manual flows."""
    frappe.db.set_value(
        "Sales Invoice",
        docname,
        {
            "custom_coupon_code": coupon_code,
            "custom_generated_coupon_code": coupon_code,
        },
        update_modified=False,
    )


def finalize_auto_generated_coupon(doc):
    """Link a generated coupon to the invoice after submit succeeds."""
    coupon_code = (doc.get("custom_generated_coupon_code") or doc.get("custom_coupon_code") or "").strip()
    if not coupon_code or not frappe.db.exists("Coupon Code", coupon_code):
        return

    current_link = frappe.db.get_value("Coupon Code", coupon_code, "custom_generated_on_order")
    if current_link != doc.name:
        frappe.db.set_value(
            "Coupon Code",
            coupon_code,
            "custom_generated_on_order",
            doc.name,
            update_modified=False,
        )

    persist_coupon_links_to_invoice(doc.name, coupon_code)


def generate_coupon_for_sales_invoice(docname: str, overrides=None) -> str:
    """Manually generate a coupon for a saved invoice."""
    doc = frappe.get_doc("Sales Invoice", docname)
    settings = get_coupon_settings()
    validate_coupon_generation_settings(settings, overrides)

    if cint(settings.allow_auto_generate_cc):
        frappe.throw(_("Manual coupon generation is only available when auto generate is disabled."))

    if not cint(settings.allow_manual_generate_cc):
        frappe.throw(_("Manual coupon generation is disabled in ArcPOS Settings."))
    if has_non_generated_coupon_on_invoice(doc):
        frappe.throw(_("This invoice already has an applied coupon code."))

    existing_coupon = get_existing_generated_coupon(doc)
    if existing_coupon:
        persist_coupon_links_to_invoice(doc.name, existing_coupon.name)
        return existing_coupon.name

    coupon = create_coupon_doc(doc, settings, overrides=overrides, defer_invoice_link=False)
    persist_coupon_links_to_invoice(doc.name, coupon.name)
    return coupon.name


def should_skip_redemption_validation(doc, coupon_doc) -> bool:
    """Skip redemption rules for the source invoice that generated the coupon."""
    generated_coupon = (doc.get("custom_generated_coupon_code") or "").strip()
    if generated_coupon and generated_coupon == coupon_doc.name:
        return True
    return coupon_doc.custom_generated_on_order == doc.name


def validate_coupon_redemption(doc, coupon_doc):
    """Validate whether a coupon can be redeemed on the invoice."""
    status = refresh_coupon_status(coupon_doc, save=False)
    if status != COUPON_STATUS_ACTIVE:
        coupon_doc.custom_status = status
        coupon_doc.save(ignore_permissions=True)
        frappe.throw(_("Coupon {0} is {1}.").format(coupon_doc.name, status.lower()))

    posting_date = getdate(doc.get("posting_date") or nowdate())
    if coupon_doc.valid_upto and posting_date > getdate(coupon_doc.valid_upto):
        coupon_doc.custom_status = COUPON_STATUS_EXPIRED
        coupon_doc.save(ignore_permissions=True)
        frappe.throw(_("Coupon {0} has expired.").format(coupon_doc.name))

    maximum_use = flt(coupon_doc.maximum_use) if coupon_doc.maximum_use is not None else None
    if maximum_use not in (None, 0) and flt(coupon_doc.used) >= maximum_use:
        coupon_doc.custom_status = COUPON_STATUS_USED
        coupon_doc.save(ignore_permissions=True)
        frappe.throw(_("Coupon {0} has already reached its usage limit.").format(coupon_doc.name))

    if not is_channel_allowed(
        doc.get("custom_order_from"),
        doc.get("custom_service_type"),
        coupon_doc.custom_redeemption_allow_on,
    ):
        frappe.throw(_("Coupon {0} is not valid for this order channel.").format(coupon_doc.name))

    if is_online_order(doc):
        minimum_subtotal = flt(coupon_doc.custom_minimum_subtotal)
        if minimum_subtotal and calculate_invoice_subtotal(doc) < minimum_subtotal:
            frappe.throw(
                _("Coupon {0} requires a minimum subtotal of {1}.").format(
                    coupon_doc.name,
                    frappe.format_value(minimum_subtotal, {"fieldtype": "Currency"}),
                )
            )


def validate_sales_invoice_coupon(doc, method=None):
    """Validate coupon redemption rules on Sales Invoice."""
    coupon_code = (doc.get("custom_coupon_code") or "").strip()
    if not coupon_code:
        return

    if not frappe.db.exists("Coupon Code", coupon_code):
        frappe.throw(_("Coupon {0} does not exist.").format(coupon_code))

    coupon_doc = frappe.get_doc("Coupon Code", coupon_code)
    if should_skip_redemption_validation(doc, coupon_doc):
        return

    validate_coupon_redemption(doc, coupon_doc)


def before_submit_sales_invoice_coupon(doc, method=None):
    """Generate and attach a coupon before submit when enabled."""
    settings = get_coupon_settings()
    if not settings:
        return

    existing_coupon = get_existing_generated_coupon(doc)
    if existing_coupon:
        link_coupon_to_invoice(doc, existing_coupon.name)
        return

    if not is_generation_allowed(doc, settings):
        return

    try:
        coupon = create_coupon_doc(doc, settings, defer_invoice_link=True)
    except (frappe.MandatoryError, frappe.ValidationError) as exc:
        frappe.log_error(
            title="Coupon Auto Generation Skipped",
            message=f"Sales Invoice: {doc.name}\nReason: {exc}",
        )
        return
    except Exception as exc:
        frappe.log_error(
            title="Coupon Auto Generation Failed",
            message=f"Sales Invoice: {doc.name}\nError: {exc}",
        )
        return

    link_coupon_to_invoice(doc, coupon.name)


def increment_coupon_usage(coupon_name: str, sales_invoice_name: str):
    """Increment coupon usage and mark the redeemed order."""
    coupon = frappe.get_doc("Coupon Code", coupon_name)
    refresh_coupon_status(coupon, save=False)

    if coupon.custom_status != COUPON_STATUS_ACTIVE:
        frappe.throw(_("Coupon {0} is not active.").format(coupon.name))

    coupon.used = flt(coupon.used) + 1
    coupon.custom_redeemed_on_order = sales_invoice_name
    coupon.custom_status = refresh_coupon_status(coupon, save=False)
    coupon.save(ignore_permissions=True)


def on_submit_sales_invoice_coupon(doc, method=None):
    """Finalize generated coupon links and redeem applied coupons on submit."""
    finalize_auto_generated_coupon(doc)

    coupon_code = (doc.get("custom_coupon_code") or "").strip()
    if not coupon_code or not frappe.db.exists("Coupon Code", coupon_code):
        return

    coupon_doc = frappe.get_doc("Coupon Code", coupon_code)
    if should_skip_redemption_validation(doc, coupon_doc):
        return

    validate_coupon_redemption(doc, coupon_doc)
    increment_coupon_usage(coupon_doc.name, doc.name)
