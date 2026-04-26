"""API endpoint for creating or updating sales invoices."""

import json

import frappe
from frappe.utils import flt, now_datetime, get_time
from .handlers.update_sales_invoice import update_sales_invoice
from excel_restaurant_pos.utils import iso_to_frappe_datetime


# parse json fields if present
def _parse_json_fields(data):
    """Parse JSON strings in data if present."""
    if isinstance(data.get("items"), str):
        data["items"] = json.loads(data["items"])
    if isinstance(data.get("taxes"), str):
        data["taxes"] = json.loads(data.get("taxes", "[]"))
    if isinstance(data.get("custom_quotes"), str):
        data["custom_quotes"] = json.loads(data.get("custom_quotes", "[]"))


# validate required fields
def _validate_required_fields(data):
    """Validate required fields for invoice creation."""
    required_fields = ["customer", "company"]
    for field in required_fields:
        if not data.get(field):
            frappe.throw(f"{field} is required for creating a sales invoice")


# validate entities
def _validate_entities(data):
    """Validate that customer and company exist."""
    if not frappe.db.exists("Customer", data.get("customer")):
        frappe.throw(f"Customer {data.get('customer')} does not exist")
    if not frappe.db.exists("Company", data.get("company")):
        frappe.throw(f"Company {data.get('company')} does not exist")


# validate items
def _validate_items(items):
    """Validate items and check if they exist in database."""
    if not items or len(items) == 0:
        frappe.throw("At least one item is required for creating a sales invoice")

    item_codes = [item_data.get("item_code") for item_data in items]
    existing = frappe.get_all(
        "Item", filters={"item_code": ["in", item_codes]}, pluck="item_code"
    )
    missing = set(item_codes) - set(existing)

    if missing:
        frappe.throw(
            f"Items not found: {', '.join(missing)}. Please check the item codes and try again."
        )


# set main fields
def _set_main_fields(sales_invoice, data):
    """Set main required fields on sales invoice."""
    sales_invoice.customer = data.get("customer")
    sales_invoice.company = data.get("company")
    sales_invoice.naming_series = data.get("naming_series") or "WEB-.YY.-.#####"
    sales_invoice.posting_date = data.get("posting_date") or frappe.utils.today()
    sales_invoice.posting_time = data.get("posting_time") or get_time(now_datetime())
    sales_invoice.due_date = data.get("due_date") or sales_invoice.posting_date


# set optional fields
def _set_optional_fields(sales_invoice, data):
    """Set optional fields on sales invoice."""
    optional_fields = [
        "customer_name",
        "discount_amount",
        "apply_discount_on",
        "update_stock",
        "custom_order_type",
        "custom_order_from",
        "custom_order_status",
        "custom_service_type",
        "custom_customer_full_name",
        "custom_mobile_no",
        "custom_email_address",
        "remarks",
        "custom_delivery_date",
        "custom_delivery_time",
        "custom_delivery_location",
        "custom_linked_table",
        "custom_party_size",
        "disable_rounded_total",
        "custom_cutlery",
        "custom_address_line1",
        "custom_city",
        "custom_state",
        "custom_pincode",
        "custom_country",
        "custom_is_deleted",
        "custom_address_instruction",
        "custom_pickup_ready",
        "custom_pickup_deadline",
        "custom_dropoff_ready",
        "custom_dropoff_deadline",
        "custom_order_schedule_type",
        "docstatus",
    ]

    for field in optional_fields:
        if data.get(field):
            setattr(sales_invoice, field, data.get(field))


# add items
def _add_items(sales_invoice, items):
    """Add items to sales invoice."""
    for item_data in items:
        if not item_data.get("item_code"):
            frappe.throw("item_code is required for all items")

        sales_invoice.append(
            "items",
            {
                "item_code": item_data.get("item_code"),
                "qty": flt(item_data.get("qty", 1)),
                "rate": flt(item_data.get("rate", 0)),
                "warehouse": item_data.get("warehouse"),
                "description": item_data.get("description"),
                "custom_parent_item": item_data.get("custom_parent_item"),
                "custom_serve_type": item_data.get("custom_serve_type"),
                "custom_order_item_status": item_data.get("custom_order_item_status"),
                "custom_if_not_available": item_data.get("custom_if_not_available"),
                "custom_special_note": item_data.get("custom_special_note"),
                "custom_is_print": item_data.get("custom_is_print"),
                "custom_guest_choice": item_data.get("custom_guest_choice"),
                "custom_is_offer_price": item_data.get("custom_is_offer_price"),
                "custom_choose_qty": item_data.get("custom_choose_qty"),
            },
        )


# add taxes
def _add_taxes(sales_invoice, taxes):
    """Add taxes to sales invoice."""
    if not taxes:
        return

    for tax_data in taxes:
        sales_invoice.append(
            "taxes",
            {
                "charge_type": tax_data.get("charge_type", "On Net Total"),
                "account_head": tax_data.get("account_head"),
                "rate": flt(tax_data.get("rate", 0)),
                "tax_amount": flt(tax_data.get("tax_amount", 0)),
                "description": tax_data.get("description", ""),
                "custom_is_tax": tax_data.get("custom_is_tax", 0),
                "custom_is_tip": tax_data.get("custom_is_tip", 0),
                "custom_is_delivery_charge": tax_data.get(
                    "custom_is_delivery_charge", 0
                ),
                "custom_is_service_charge": tax_data.get("custom_is_service_charge", 0),
            },
        )


# add custom quotes
def _add_custom_quotes(sales_invoice, custom_quotes):
    """Add custom quotes to sales invoice."""
    if not custom_quotes:
        return

    for custom_quote in custom_quotes:
        sales_invoice.append(
            "custom_quotes",
            {
                "delivery_quote_id": custom_quote.get("delivery_quote_id"),
                "created": iso_to_frappe_datetime(custom_quote.get("created")),
                "currency": custom_quote.get("currency"),
                "currency_type": custom_quote.get("currency_type"),
                "dropoff_eta": iso_to_frappe_datetime(custom_quote.get("dropoff_eta")),
                "duration": custom_quote.get("duration"),
                "fee": custom_quote.get("fee"),
                "expires": iso_to_frappe_datetime(custom_quote.get("expires")),
                "dropoff_deadline": iso_to_frappe_datetime(
                    custom_quote.get("dropoff_deadline")
                ),
                "pickup_duration": custom_quote.get("pickup_duration"),
            },
        )


# add payments
def _add_payments(sales_invoice, payments):
    """Add payments to sales invoice."""
    if not payments:
        return

    for payment in payments:
        sales_invoice.append(
            "payments",
            {
                "mode_of_payment": payment.get("mode_of_payment"),
                "amount": flt(payment.get("amount", 0)),
            },
        )


@frappe.whitelist(allow_guest=True)
def add_or_update_invoice():
    """
    Create a new Sales Invoice from user-provided data
    Uses default Frappe creation method with validation
    Allows guest access by using ignore_permissions=True
    """
    data = frappe.form_dict
    _parse_json_fields(data)

    invoice_name = data.get("invoice_name")
    if invoice_name:
        updated = update_sales_invoice(invoice_name, items=data.get("items", []))
        return updated.as_dict()

    items = data.get("items", [])
    _validate_required_fields(data)
    _validate_items(items)
    _validate_entities(data)

    sales_invoice = frappe.new_doc("Sales Invoice")
    _set_main_fields(sales_invoice, data)
    _set_optional_fields(sales_invoice, data)
    _add_items(sales_invoice, items)
    _add_custom_quotes(sales_invoice, data.get("custom_quotes"))

    _add_taxes(sales_invoice, data.get("taxes"))
    # _add_payments(sales_invoice, data.get("payments"))

    # sales_invoice.is_pos = 1
    sales_invoice.save(ignore_permissions=True)

    return sales_invoice.as_dict()
