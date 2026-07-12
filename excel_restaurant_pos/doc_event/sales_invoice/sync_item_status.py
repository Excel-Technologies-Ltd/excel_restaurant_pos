"""Sync Sales Invoice Item status with the parent order status."""

import frappe

# Statuses that the Sales Invoice carries but a Sales Invoice Item cannot hold.
# These are handled by their own dedicated handlers (e.g. payment_change_handler
# maps "Closed" -> item "Served"), so we skip them here.
UNSUPPORTED_ITEM_STATUSES = {"Closed"}


def sync_item_status_with_order_status(doc, method=None):
    """When ``custom_order_status`` changes, mirror it onto every item's
    ``custom_order_item_status``.

    Runs on ``validate`` so the item changes persist within the same save.
    """
    if not doc.has_value_changed("custom_order_status"):
        return

    new_status = doc.get("custom_order_status")
    if not new_status or new_status in UNSUPPORTED_ITEM_STATUSES:
        return

    for item in doc.items:
        if item.get("custom_order_item_status") != new_status:
            item.custom_order_item_status = new_status
