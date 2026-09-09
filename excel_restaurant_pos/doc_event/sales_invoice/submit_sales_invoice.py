"""Document event handlers for Sales Invoice submission."""

import frappe

from .handlers.create_feedback import create_feedback
from .handlers.create_payment_entry import create_payment_entry
from .handlers.update_item_sales_count import update_item_sales_count


def submit_sales_invoice(doc, method: str):
    """
    Submit Sales Invoice
    Args:
        doc: The Sales Invoice document.
        method: The method being called.
    tasks:
        Create arcpos feedback doc (in short queue)
        Increase item sales count
    """
    # enqueue_after_commit on all three: a worker picks the job up on its own
    # database connection, so anything queued before this transaction commits
    # can run against an invoice that is not visible yet -- create_payment_entry
    # re-reads it by name and fails with "not found". The window widens with the
    # work done inside submit, which is why an invoice that also sells a gift
    # card (a Coupon Code insert plus coupon saves) loses the race far more
    # reliably than a plain one. The same guard, for the same reason, is on the
    # handlers in change_sales_invoice.
    if doc.custom_with_arcpos_payment:
        frappe.enqueue(
            create_payment_entry,
            queue="short",
            enqueue_after_commit=True,
            sales_invoice=doc.name,
        )

    # Enqueue feedback doc creation in short queue
    frappe.enqueue(
        create_feedback,
        queue="short",
        enqueue_after_commit=True,
        doc_dict=doc.as_dict(),
    )

    # Enqueue item sales count update in short queue (bulk update)
    item_codes_and_qty = [(item.item_code, item.qty) for item in doc.items]
    frappe.enqueue(
        update_item_sales_count,
        queue="short",
        enqueue_after_commit=True,
        item_codes_and_qty=item_codes_and_qty,
    )
