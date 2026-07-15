"""Document event handlers for Sales Invoice changes."""

import frappe
from datetime import timedelta
from frappe.utils import now_datetime, get_datetime
from frappe_uberdirect.utils.background_jobs import enqueue_delayed

from .handlers.schedule_status_handler import schedule_status_handler
from .handlers.payment_change_handler import payment_change_handler
from .handlers.order_change_handler import order_change_handler
from .handlers.order_cancel_handler import order_cancel_handler
from .handlers.customer_change_handler import customer_change_handler
from .handlers.change_delete_handler import change_delete_handler
from .handlers.delayed_order_status_handler import delayed_order_status_handler
from .handlers.create_promotion_journal import create_promotion_journal
from .handlers.uber_eats_status_handler import uber_eats_status_handler


def change_sales_invoice(doc, method: str):
    """
    Validate Sales Invoice
    """
    # get order status
    order_status = doc.get("custom_order_status", "").lower()
    doc_status = doc.get("status", "").lower()
    is_deleted = doc.get("custom_is_deleted", False)

    # payment change logic
    # enqueue_after_commit: these handlers re-read the invoice on a separate
    # connection. Enqueued before the commit they can observe the pre-commit row,
    # see a status that is not yet Paid, and silently give up.
    if doc.has_value_changed("status") and doc_status == "paid":
        frappe.log_error("Status changed", f"Status changed to {doc_status}")
        frappe.enqueue(
            create_promotion_journal,
            queue="short",
            enqueue_after_commit=True,
            invoice_name=doc.name,
        )
        frappe.enqueue(
            payment_change_handler,
            queue="default",
            enqueue_after_commit=True,
            invoice_name=doc.name,
        )

    # cancelled status logic
    if doc.has_value_changed("status") and doc_status == "cancelled":
        msg = f"Status changed to {doc_status}"
        frappe.log_error("Status changed", msg)
        frappe.enqueue(
            order_cancel_handler,
            queue="default",
            enqueue_after_commit=True,
            invoice_name=doc.name,
        )

    # order status change logic
    is_close_or_rejected = order_status in ["closed", "rejected"]
    if doc.has_value_changed("custom_order_status") and is_close_or_rejected:
        msg = f"Order status changed to {order_status}"
        frappe.log_error("Order status changed", msg)
        frappe.enqueue(
            order_change_handler,
            queue="default",
            enqueue_after_commit=True,
            invoice_name=doc.name,
        )

    # scheduled order status change logic
    if doc.has_value_changed("custom_order_status") and order_status == "scheduled":
        schedule_status_handler(doc=doc)

    # customer change logic
    if doc.has_value_changed("customer"):
        customer_change_handler(doc=doc)

    # is deleted change logic
    if doc.has_value_changed("custom_is_deleted") and is_deleted:
        frappe.enqueue(change_delete_handler, queue="short", invoice_name=doc.name)

    # Uber Eats status sync
    order_from = (doc.get("custom_order_from") or "").lower()
    if doc.has_value_changed("custom_order_status") and order_from == "ubereats":
        frappe.enqueue(
            uber_eats_status_handler, queue="default", invoice_name=doc.name
        )

    # table realease logic here
    # table_name = doc.custom_linked_table
    # order_from = None
    # if doc.custom_order_from:
    #     order_from = doc.custom_order_from.lower()

    # # generate args
    # args = {"table_name": table_name, "sales_invoice": doc.name}

    # # if the sales invoice is paid and the order is from a table, enqueue the table release
    # if doc.status == "Paid":
    #     frappe.db.set_value("Sales Invoice", doc.name, "custom_order_status", "Closed")
    #     if table_name and order_from == "table":
    #         frappe.enqueue(handle_table_release, queue="short", **args)

    # release_status = ["Closed", "Rejected"]
    # if doc.custom_order_status in release_status:
    #     if table_name and order_from == "table":
    #         frappe.enqueue(handle_table_release, queue="short", **args)
