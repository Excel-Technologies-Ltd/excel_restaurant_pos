"""Scheduled sync: pull all Clover payments and upsert into Clover Payment doctype."""

import frappe
from frappe.utils import now_datetime

from .clover_api import get_payments, get_settings


def _cents_to_currency(cents):
    return (cents or 0) / 100.0


def _ms_to_datetime(ms):
    """Convert Clover epoch-milliseconds to a Python datetime."""
    if not ms:
        return None
    import datetime
    return datetime.datetime.utcfromtimestamp(ms / 1000)


def _upsert_payment(payment, merchant_id):
    """Insert or skip a single Clover payment record (idempotent)."""
    payment_id = payment.get("id")
    if not payment_id:
        return

    if frappe.db.exists("Clover Payment", {"payment_id": payment_id}):
        return  # already synced — skip

    order = payment.get("order") or {}
    tender = payment.get("tender") or {}
    employee = payment.get("employee") or {}

    doc = frappe.new_doc("Clover Payment")
    doc.payment_id = payment_id
    doc.merchant_id = merchant_id
    doc.result = payment.get("result", "")
    doc.offline = 1 if payment.get("offline") else 0

    doc.order_id = order.get("id", "")
    doc.order_title = order.get("title", "")
    doc.order_state = order.get("state", "")
    doc.order_currency = order.get("currency", "")

    doc.tender_id = tender.get("id", "")
    doc.tender_label = tender.get("label", "")
    doc.employee_id = employee.get("id", "")

    doc.amount = _cents_to_currency(payment.get("amount"))
    doc.tip_amount = _cents_to_currency(payment.get("tipAmount"))
    doc.cashback_amount = _cents_to_currency(payment.get("cashbackAmount"))

    doc.created_time = _ms_to_datetime(payment.get("createdTime"))
    doc.modified_time = _ms_to_datetime(payment.get("modifiedTime"))

    doc.raw_payload = frappe.as_json(payment)

    doc.insert(ignore_permissions=True)


def sync_clover_payments():
    """Fetch all pages of Clover payments and save new ones to Clover Payment doctype.

    Scheduled daily at 12:05 AM via hooks.py scheduler_events.
    Safe to run manually at any time — duplicate payments are skipped.
    """
    settings = get_settings()
    merchant_id = settings.merchant_id

    if not settings.enabled:
        frappe.logger().info("Clover sync skipped: integration not enabled")
        return

    if not merchant_id:
        frappe.logger().warning("Clover sync skipped: no merchant_id configured")
        return

    limit = 100
    offset = 0
    total_synced = 0
    total_skipped = 0

    frappe.logger().info(f"Clover payment sync started for merchant {merchant_id}")

    while True:
        data = get_payments(merchant_id=merchant_id, limit=limit, offset=offset)
        elements = data.get("elements", [])

        if not elements:
            break

        for payment in elements:
            payment_id = payment.get("id")
            if frappe.db.exists("Clover Payment", {"payment_id": payment_id}):
                total_skipped += 1
            else:
                _upsert_payment(payment, merchant_id)
                total_synced += 1

        # If we got fewer than limit results, we've reached the last page
        if len(elements) < limit:
            break

        offset += limit

    frappe.db.commit()
    frappe.logger().info(
        f"Clover payment sync done: {total_synced} new, {total_skipped} skipped"
    )
    return {"synced": total_synced, "skipped": total_skipped}
