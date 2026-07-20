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
    """Return True for website pickup or delivery orders."""
    return is_channel_allowed(
        doc.get("custom_order_from"),
        doc.get("custom_service_type"),
        "Only Online",
    )


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


def get_coupon_linked_email(doc=None, overrides=None) -> str:
    """Resolve the coupon's linked email using the requested priority."""
    overrides = overrides or {}
    override_email = (overrides.get("linked_email") or "").strip()
    if override_email:
        return override_email

    if not doc:
        return ""

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
    coupon_name = (doc.get("custom_generated_coupon_code") or "").strip()
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


def is_generation_allowed(doc, settings) -> bool:
    """Check whether the invoice is eligible for coupon generation.

    Every condition configured in ArcPOS Settings has to hold: generation must be
    enabled, the order's channel must match auto_generate_on, and the invoice must
    reach minimum_subtotal_generate. The minimum applies to every allowed channel
    -- it is the channel filter, not the minimum, that is channel specific.
    """
    if not settings or not cint(settings.allow_auto_generate_cc):
        return False

    if not is_channel_allowed(
        doc.get("custom_order_from"), doc.get("custom_service_type"), settings.auto_generate_on
    ):
        return False

    minimum_subtotal = flt(settings.minimum_subtotal_generate)
    if minimum_subtotal and flt(doc.get("net_total")) < minimum_subtotal:
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
    if not defer_invoice_link and doc and doc.get("name"):
        coupon_fields["custom_generated_on_order"] = doc.name

    coupon_doc = frappe.get_doc(coupon_fields)

    # custom_generated_on_order is deferred to on_submit above, so flag the
    # association for hooks that must know this coupon belongs to an invoice.
    if doc and doc.get("name"):
        coupon_doc.flags.generated_for_invoice = doc.name

    coupon_doc.insert(ignore_permissions=True)
    return coupon_doc


def link_coupon_to_invoice(doc, coupon_code: str):
    """Attach a generated coupon to the invoice in-memory (not an applied redemption)."""
    doc.custom_generated_coupon_code = coupon_code
    if (doc.get("custom_coupon_code") or "").strip() == coupon_code:
        doc.custom_coupon_code = None


def persist_coupon_links_to_invoice(docname: str, coupon_code: str):
    """Persist the generated coupon link on the invoice."""
    values = {"custom_generated_coupon_code": coupon_code}

    # Clear legacy rows where generation incorrectly copied into custom_coupon_code.
    applied_coupon = (frappe.db.get_value("Sales Invoice", docname, "custom_coupon_code") or "").strip()
    if applied_coupon == coupon_code:
        values["custom_coupon_code"] = None

    frappe.db.set_value("Sales Invoice", docname, values, update_modified=False)


def finalize_auto_generated_coupon(doc):
    """Link a generated coupon to the invoice after submit succeeds."""
    coupon_code = (doc.get("custom_generated_coupon_code") or "").strip()
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


def validate_manual_coupon_generation(settings, overrides=None):
    """Validate ArcPOS settings required for manual coupon generation."""
    validate_coupon_generation_settings(settings, overrides)

    if not cint(settings.allow_manual_generate_cc):
        frappe.throw(_("Manual coupon generation is disabled in ArcPOS Settings."))


def generate_manual_coupon(overrides=None, sales_invoice: str | None = None) -> str:
    """Manually generate a coupon, optionally linked to a Sales Invoice."""
    settings = get_coupon_settings()
    validate_manual_coupon_generation(settings, overrides)

    if sales_invoice:
        if not frappe.db.exists("Sales Invoice", sales_invoice):
            frappe.throw(
                _("Sales Invoice {0} does not exist.").format(sales_invoice),
                frappe.DoesNotExistError,
            )

        doc = frappe.get_doc("Sales Invoice", sales_invoice)
        existing_coupon = get_existing_generated_coupon(doc)
        if existing_coupon:
            persist_coupon_links_to_invoice(doc.name, existing_coupon.name)
            return existing_coupon.name

        coupon = create_coupon_doc(doc, settings, overrides=overrides, defer_invoice_link=False)
        persist_coupon_links_to_invoice(doc.name, coupon.name)
        return coupon.name

    coupon = create_coupon_doc(frappe._dict(), settings, overrides=overrides, defer_invoice_link=False)
    return coupon.name


def generate_coupon_for_sales_invoice(docname: str, overrides=None) -> str:
    """Manually generate a coupon for a saved invoice."""
    return generate_manual_coupon(overrides=overrides, sales_invoice=docname)


def normalize_coupon_name(value) -> str:
    """Resolve a Coupon Code document name from a link value or coupon string."""
    coupon_value = (value or "").strip()
    if not coupon_value:
        return ""

    if frappe.db.exists("Coupon Code", coupon_value):
        return coupon_value

    return frappe.db.get_value("Coupon Code", {"coupon_code": coupon_value}, "name") or ""


def resolve_applied_coupon_code(doc) -> str:
    """Return the coupon redeemed on this invoice from the in-memory document only."""
    for fieldname in ("custom_coupon_code", "coupon_code"):
        coupon_name = normalize_coupon_name(doc.get(fieldname))
        if coupon_name:
            return coupon_name
    return ""


def is_generated_coupon_on_invoice(doc, coupon_doc) -> bool:
    """Return True when this coupon was generated from the same invoice."""
    generated_coupon = (doc.get("custom_generated_coupon_code") or "").strip()
    if generated_coupon and generated_coupon == coupon_doc.name:
        return True
    return coupon_doc.custom_generated_on_order == doc.name


def should_skip_redemption_validation(doc, coupon_doc) -> bool:
    """Skip redemption rules when the invoice generated this coupon, not redeemed it."""
    applied_coupon = resolve_applied_coupon_code(doc)
    if applied_coupon and applied_coupon != coupon_doc.name:
        return False
    return is_generated_coupon_on_invoice(doc, coupon_doc)


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


def _apply_coupon_custom_discount(doc, coupon_doc):
    """Apply coupon discount from custom fields when pricing rule is not used."""
    discount_type = (coupon_doc.custom_discount_type or "").strip().lower()
    discount_value = flt(coupon_doc.custom_discount_amount)
    if not discount_value:
        return False

    doc.apply_discount_on = doc.apply_discount_on or "Net Total"
    if discount_type in ("percentage", "percent"):
        doc.additional_discount_percentage = discount_value
        doc.discount_amount = 0
    else:
        # A flat discount can never exceed what it is applied on -- otherwise the
        # total would go negative (or ERPNext would reject it). Cap it so the
        # invoice simply floors at zero.
        doc.discount_amount = _cap_flat_discount(doc, discount_value)
        doc.additional_discount_percentage = 0
    return True


def _get_stored_applied_coupon(doc) -> str:
    """Return the coupon code last saved on the invoice."""
    if not doc.name:
        return ""
    return normalize_coupon_name(frappe.db.get_value("Sales Invoice", doc.name, "custom_coupon_code"))


def _load_coupon(coupon):
    """Return a Coupon Code doc from a name or doc, or None when unresolvable."""
    if not coupon:
        return None
    if isinstance(coupon, str):
        if not frappe.db.exists("Coupon Code", coupon):
            return None
        return frappe.get_doc("Coupon Code", coupon)
    return coupon


def _discount_base(doc) -> float:
    """The amount a transaction-level discount is applied on, per apply_discount_on."""
    if (doc.get("apply_discount_on") or "Grand Total") == "Grand Total":
        base = doc.get("grand_total") or doc.get("total")
    else:
        base = doc.get("net_total") or doc.get("total")
    return flt(base)


def _cap_flat_discount(doc, discount_value: float) -> float:
    """Never let a flat discount exceed the amount it applies on, so the invoice
    floors at zero instead of going negative or erroring."""
    discount_value = flt(discount_value)
    base = _discount_base(doc)
    if base and discount_value > base:
        return base
    return discount_value


def _clear_coupon_transaction_discount(doc, removed_coupon):
    """Clear only the transaction-level discount THIS coupon set, and only while
    it still holds that coupon's value.

    `additional_discount_percentage` / `discount_amount` are shared with manual
    discounts. A percentage coupon lives in the first field, a flat coupon in the
    second. We clear a field only when its current value matches what the coupon
    applied -- so a manual discount the user typed (a different value, or the other
    field) is never destroyed when the coupon is removed. When the coupon cannot be
    resolved we fall back to the full reset so a coupon discount cannot linger.
    """
    coupon = _load_coupon(removed_coupon)
    if not coupon:
        doc.discount_amount = 0
        doc.additional_discount_percentage = 0
        return

    discount_value = flt(coupon.custom_discount_amount)
    if not discount_value:
        return

    if _normalize_discount_type(coupon.custom_discount_type) == "percentage":
        if flt(doc.additional_discount_percentage) == discount_value:
            doc.additional_discount_percentage = 0
    elif flt(doc.discount_amount) in (discount_value, _cap_flat_discount(doc, discount_value)):
        doc.discount_amount = 0


def _reset_coupon_discount_state(doc, removed_coupon=None):
    """Undo a coupon's discount on the invoice.

    The coupon link is always cleared. The shared transaction-level discount is
    only cleared when it still holds the removed coupon's value, so a manual
    discount is never destroyed. Item rows are reset only when they carry a
    coupon-attached pricing rule, leaving manually-priced items alone. Pass
    `removed_coupon` (name or doc) so the value check can run.
    """
    doc.custom_coupon_code = None
    doc.coupon_code = None

    _clear_coupon_transaction_discount(doc, removed_coupon)

    for item in doc.get("items") or []:
        if not item.get("pricing_rules"):
            continue
        item.pricing_rules = ""
        item.discount_percentage = 0
        item.discount_amount = 0
        if flt(item.get("price_list_rate")):
            item.rate = flt(item.price_list_rate)

    doc.flags.coupon_discount_applied_for = None


def preview_coupon_discount(doc, coupon_doc) -> dict:
    """Return the discount type and estimated value for a coupon on an invoice."""
    discount_type = (coupon_doc.custom_discount_type or "").strip().lower()
    discount_amount = flt(coupon_doc.custom_discount_amount)
    subtotal = calculate_invoice_subtotal(doc)

    if discount_type in ("percentage", "percent"):
        return {
            "discount_type": "percentage",
            "discount_amount": discount_amount,
            "discount_value": flt(subtotal * discount_amount / 100) if discount_amount else 0,
        }

    return {
        "discount_type": "flat",
        "discount_amount": discount_amount,
        "discount_value": discount_amount,
    }


def ensure_draft_sales_invoice(doc):
    """Allow coupon changes only while the invoice is still a draft."""
    if cint(doc.docstatus) != 0:
        frappe.throw(_("Coupon changes are only allowed on draft Sales Invoices."))


def _normalize_discount_type(discount_type: str | None) -> str:
    value = (discount_type or "").strip().lower()
    if value == "flat amount":
        return "flat"
    if value in ("percentage", "percent"):
        return "percentage"
    return value


def assert_coupon_globally_valid(coupon_doc):
    """Validate coupon status, validity dates, and usage without invoice context."""
    status = refresh_coupon_status(coupon_doc, save=True)
    if status != COUPON_STATUS_ACTIVE:
        frappe.throw(_("Coupon {0} is {1}.").format(coupon_doc.name, status.lower()))

    today = getdate(nowdate())
    if coupon_doc.valid_from and today < getdate(coupon_doc.valid_from):
        frappe.throw(_("Coupon {0} is not yet valid.").format(coupon_doc.name))

    if coupon_doc.valid_upto and today > getdate(coupon_doc.valid_upto):
        coupon_doc.custom_status = COUPON_STATUS_EXPIRED
        coupon_doc.save(ignore_permissions=True)
        frappe.throw(_("Coupon {0} has expired.").format(coupon_doc.name))

    maximum_use = flt(coupon_doc.maximum_use) if coupon_doc.maximum_use is not None else None
    if maximum_use not in (None, 0) and flt(coupon_doc.used) >= maximum_use:
        coupon_doc.custom_status = COUPON_STATUS_USED
        coupon_doc.save(ignore_permissions=True)
        frappe.throw(_("Coupon {0} has already reached its usage limit.").format(coupon_doc.name))


def validate_coupon_globally(coupon_code: str) -> dict:
    """Validate a coupon without Sales Invoice context."""
    coupon_name = normalize_coupon_name(coupon_code)
    if not coupon_name:
        frappe.throw(_("Coupon {0} does not exist.").format(coupon_code), frappe.DoesNotExistError)

    coupon_doc = frappe.get_doc("Coupon Code", coupon_name)
    assert_coupon_globally_valid(coupon_doc)

    return {
        "status": "success",
        "valid": True,
        "coupon_code": coupon_doc.coupon_code,
        "coupon_name": coupon_doc.name,
        "coupon_status": coupon_doc.custom_status,
        "discount_type": _normalize_discount_type(coupon_doc.custom_discount_type),
        "discount_amount": coupon_doc.custom_discount_amount,
        "valid_from": coupon_doc.valid_from,
        "valid_upto": coupon_doc.valid_upto,
        "maximum_use": coupon_doc.maximum_use,
        "used": coupon_doc.used,
        "minimum_subtotal": coupon_doc.custom_minimum_subtotal,
        "redemption_allow_on": coupon_doc.custom_redeemption_allow_on,
        "qr_code": coupon_doc.custom_qr_code,
        "barcode": coupon_doc.custom_barcode,
    }


def verify_coupon_for_sales_invoice(docname: str, coupon_code: str) -> dict:
    """Validate a coupon for an invoice without applying it."""
    doc = frappe.get_doc("Sales Invoice", docname)
    ensure_draft_sales_invoice(doc)

    coupon_name = normalize_coupon_name(coupon_code)
    if not coupon_name:
        frappe.throw(_("Coupon {0} does not exist.").format(coupon_code))

    coupon_doc = frappe.get_doc("Coupon Code", coupon_name)
    if should_skip_redemption_validation(doc, coupon_doc):
        frappe.throw(_("This coupon cannot be redeemed on the invoice that generated it."))

    validate_coupon_redemption(doc, coupon_doc)
    preview = preview_coupon_discount(doc, coupon_doc)

    return {
        "status": "success",
        "valid": True,
        "sales_invoice": doc.name,
        "coupon_code": coupon_doc.coupon_code,
        "coupon_name": coupon_doc.name,
        "coupon_status": coupon_doc.custom_status,
        "discount_type": preview["discount_type"],
        "discount_amount": preview["discount_amount"],
        "discount_value": preview["discount_value"],
        "valid_from": coupon_doc.valid_from,
        "valid_upto": coupon_doc.valid_upto,
        "maximum_use": coupon_doc.maximum_use,
        "used": coupon_doc.used,
        "minimum_subtotal": coupon_doc.custom_minimum_subtotal,
        "redemption_allow_on": coupon_doc.custom_redeemption_allow_on,
        "qr_code": coupon_doc.custom_qr_code,
        "barcode": coupon_doc.custom_barcode,
    }


def apply_coupon_to_sales_invoice(docname: str, coupon_code: str) -> dict:
    """Validate and apply a coupon to a draft Sales Invoice."""
    doc = frappe.get_doc("Sales Invoice", docname)
    ensure_draft_sales_invoice(doc)

    coupon_name = normalize_coupon_name(coupon_code)
    if not coupon_name:
        frappe.throw(_("Coupon {0} does not exist.").format(coupon_code))

    coupon_doc = frappe.get_doc("Coupon Code", coupon_name)
    if should_skip_redemption_validation(doc, coupon_doc):
        frappe.throw(_("This coupon cannot be redeemed on the invoice that generated it."))

    validate_coupon_redemption(doc, coupon_doc)

    stored_coupon = _get_stored_applied_coupon(doc)
    if stored_coupon and stored_coupon != coupon_name:
        _reset_coupon_discount_state(doc, removed_coupon=stored_coupon)

    doc.custom_coupon_code = coupon_name
    doc.flags.coupon_discount_applied_for = None
    apply_sales_invoice_coupon_discount(doc, force=True)
    doc.save(ignore_permissions=True)

    preview = preview_coupon_discount(doc, coupon_doc)
    return {
        "status": "success",
        "applied": True,
        "sales_invoice": doc.name,
        "coupon_code": coupon_doc.coupon_code,
        "coupon_name": coupon_doc.name,
        "discount_type": preview["discount_type"],
        "discount_amount": preview["discount_amount"],
        "discount_value": preview["discount_value"],
        "invoice_discount_amount": flt(doc.discount_amount),
        "invoice_additional_discount_percentage": flt(doc.additional_discount_percentage),
        "grand_total": flt(doc.grand_total),
    }


def discard_coupon_from_sales_invoice(docname: str) -> dict:
    """Remove an applied coupon and its discount from a draft Sales Invoice."""
    doc = frappe.get_doc("Sales Invoice", docname)
    ensure_draft_sales_invoice(doc)

    previous_coupon = resolve_applied_coupon_code(doc) or _get_stored_applied_coupon(doc)
    _reset_coupon_discount_state(doc, removed_coupon=previous_coupon)
    doc.calculate_taxes_and_totals()
    doc.save(ignore_permissions=True)

    return {
        "status": "success",
        "discarded": True,
        "sales_invoice": doc.name,
        "previous_coupon_code": previous_coupon or None,
        "discount_amount": flt(doc.discount_amount),
        "grand_total": flt(doc.grand_total),
    }


def apply_sales_invoice_coupon_discount(doc, method=None, force=False):
    """Apply the coupon's flat/percentage discount to a Sales Invoice.

    Coupons carry a Pricing Rule only to satisfy a required field; it never drives
    the discount. The discount always comes from the coupon's own
    custom_discount_type / custom_discount_amount.
    """
    coupon_code = resolve_applied_coupon_code(doc)
    if not coupon_code:
        stored_coupon = _get_stored_applied_coupon(doc)
        if stored_coupon:
            _reset_coupon_discount_state(doc, removed_coupon=stored_coupon)
            doc.calculate_taxes_and_totals()
        return

    stored_coupon = _get_stored_applied_coupon(doc)
    coupon_changed = bool(stored_coupon and stored_coupon != coupon_code)

    if not force and doc.flags.get("coupon_discount_applied_for") == coupon_code:
        return

    if force or coupon_changed:
        _reset_coupon_discount_state(doc, removed_coupon=stored_coupon)

    doc.custom_coupon_code = coupon_code

    coupon_doc = frappe.get_doc("Coupon Code", coupon_code)
    if should_skip_redemption_validation(doc, coupon_doc):
        return

    # ERPNext pricing helpers read `coupon_code`, not `custom_coupon_code`.
    doc.coupon_code = coupon_code

    if _apply_coupon_custom_discount(doc, coupon_doc):
        doc.calculate_taxes_and_totals()

    doc.flags.coupon_discount_applied_for = coupon_code


def validate_sales_invoice_coupon(doc, method=None):
    """Validate coupon redemption rules on Sales Invoice."""
    coupon_code = resolve_applied_coupon_code(doc)
    if not coupon_code:
        return

    coupon_doc = frappe.get_doc("Coupon Code", coupon_code)
    if should_skip_redemption_validation(doc, coupon_doc):
        return

    validate_coupon_redemption(doc, coupon_doc)


def before_submit_sales_invoice_coupon(doc, method=None):
    """Generate and attach a coupon before submit when enabled."""
    coupon_code = resolve_applied_coupon_code(doc)
    if coupon_code:
        doc.custom_coupon_code = coupon_code

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
    status = refresh_coupon_status(coupon, save=False)

    frappe.db.set_value(
        "Coupon Code",
        coupon_name,
        {
            "used": coupon.used,
            "custom_redeemed_on_order": sales_invoice_name,
            "custom_status": status,
        },
        update_modified=True,
    )


def on_submit_sales_invoice_coupon(doc, method=None):
    """Finalize generated coupon links and redeem applied coupons on submit."""
    finalize_auto_generated_coupon(doc)

    coupon_code = resolve_applied_coupon_code(doc)
    if not coupon_code:
        return

    coupon_doc = frappe.get_doc("Coupon Code", coupon_code)
    if should_skip_redemption_validation(doc, coupon_doc):
        return

    validate_coupon_redemption(doc, coupon_doc)
    increment_coupon_usage(coupon_doc.name, doc.name)

    if not doc.get("custom_coupon_code"):
        frappe.db.set_value(
            "Sales Invoice",
            doc.name,
            "custom_coupon_code",
            coupon_code,
            update_modified=False,
        )
