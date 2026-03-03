"""Whitelisted API endpoints for Uber Eats order management."""

import frappe


@frappe.whitelist()
def get_orders(store_id=None):
    """Get active (CREATED) orders from Uber Eats.

    Args:
        store_id: Optional store UUID, defaults to configured store
    """
    from .uber_eats_api import get_active_orders

    return get_active_orders(store_id=store_id)


@frappe.whitelist()
def get_canceled_orders(store_id=None):
    """Get canceled orders from Uber Eats.

    Args:
        store_id: Optional store UUID, defaults to configured store
    """
    from .uber_eats_api import get_canceled_orders as _get_canceled_orders

    return _get_canceled_orders(store_id=store_id)


@frappe.whitelist()
def get_order(order_id):
    """Get full order details from Uber Eats.

    Args:
        order_id: Uber Eats order UUID
    """
    if not order_id:
        frappe.throw("order_id is required")

    from .uber_eats_api import get_order_details

    return get_order_details(order_id)


@frappe.whitelist()
def cancel_uber_eats_order(order_id, reason="OTHER", details=""):
    """Cancel an accepted order on Uber Eats.

    Args:
        order_id: Uber Eats order UUID
        reason: One of OUT_OF_ITEMS, KITCHEN_CLOSED, CUSTOMER_CALLED_TO_CANCEL,
                RESTAURANT_TOO_BUSY, CANNOT_COMPLETE_CUSTOMER_NOTE, OTHER
        details: Human-readable explanation (required when reason is OTHER)
    """
    if not order_id:
        frappe.throw("order_id is required")

    valid_reasons = (
        "OUT_OF_ITEMS", "KITCHEN_CLOSED", "CUSTOMER_CALLED_TO_CANCEL",
        "RESTAURANT_TOO_BUSY", "CANNOT_COMPLETE_CUSTOMER_NOTE", "OTHER",
    )
    if reason and reason.upper() not in valid_reasons:
        frappe.throw(f"Invalid cancel reason '{reason}'. Must be one of: {', '.join(valid_reasons)}")
    reason = reason.upper() if reason else "OTHER"

    from .uber_eats_api import cancel_order

    cancel_order(order_id, reason=reason, details=details)
    return {"status": "cancelled", "order_id": order_id}


@frappe.whitelist()
def accept_uber_eats_order(order_id, external_reference_id=None, estimated_ready_for_pickup_at=None):
    """Accept an order on Uber Eats.

    Uber Eats has no separate update-prep-time endpoint, so estimated_ready_for_pickup_at
    must be provided here at acceptance time if you want to communicate prep time.

    Args:
        order_id: Uber Eats order UUID
        external_reference_id: Optional POS invoice name to link back
        estimated_ready_for_pickup_at: Optional ISO 8601 UTC timestamp e.g. "2026-02-22T15:00:00Z"
    """
    if not order_id:
        frappe.throw("order_id is required")

    from datetime import datetime as _dt, timezone as _tz
    from .uber_eats_api import accept_order

    iso_utc = None
    naive_utc = None
    if estimated_ready_for_pickup_at:
        try:
            dt = _dt.fromisoformat(estimated_ready_for_pickup_at.replace("Z", "+00:00"))
            dt_utc = dt.astimezone(_tz.utc)
            iso_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            naive_utc = dt_utc.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            frappe.throw(
                f"Invalid datetime format '{estimated_ready_for_pickup_at}'. "
                "Use ISO 8601, e.g. '2026-02-22T15:00:00Z'."
            )

    accept_order(order_id, external_reference_id=external_reference_id, estimated_ready_for_pickup_at=iso_utc)

    # Sync current_state and estimated ready time to the local Channel Order
    channel_order_name = frappe.db.get_value("Channel Order", {"order_id": order_id}, "name")
    if channel_order_name:
        updates = {"current_state": "ACCEPTED"}
        if naive_utc:
            updates["estimated_ready_for_pickup_at"] = naive_utc
        frappe.db.set_value("Channel Order", channel_order_name, updates)
        frappe.db.commit()

    return {"status": "accepted", "order_id": order_id}


@frappe.whitelist()
def deny_uber_eats_order(order_id, reason_code="OTHER", explanation="Order denied by restaurant"):
    """Deny/reject an order on Uber Eats.

    Args:
        order_id: Uber Eats order UUID
        reason_code: One of STORE_CLOSED, POS_NOT_READY, POS_OFFLINE,
                     ITEM_AVAILABILITY, MISSING_ITEM, MISSING_INFO,
                     PRICING, CAPACITY, ADDRESS, SPECIAL_INSTRUCTIONS, OTHER
        explanation: Human-readable denial reason
    """
    if not order_id:
        frappe.throw("order_id is required")

    from .uber_eats_api import deny_order

    deny_order(order_id, reason_code=reason_code, explanation=explanation)

    # Update current_state on the local Channel Order
    channel_order_name = frappe.db.get_value("Channel Order", {"order_id": order_id}, "name")
    if channel_order_name:
        frappe.db.set_value("Channel Order", channel_order_name, "current_state", "REJECTED")
        frappe.db.commit()

    return {"status": "denied", "order_id": order_id}


@frappe.whitelist()
def update_estimated_ready_time(order_id, estimated_ready_for_pickup_at):
    """Update estimated_ready_for_pickup_at on the local Channel Order record.

    NOTE: Uber Eats does not provide a separate endpoint to update prep time after
    acceptance. The estimated ready time can only be sent to Uber Eats at the moment
    of acceptance via accept_uber_eats_order. This endpoint updates the local
    Channel Order field only.

    Args:
        order_id: Uber Eats order UUID
        estimated_ready_for_pickup_at: ISO 8601 timestamp (e.g. "2026-02-22T15:00:00Z")
    """
    if not order_id:
        frappe.throw("order_id is required")
    if not estimated_ready_for_pickup_at:
        frappe.throw("estimated_ready_for_pickup_at is required")

    from datetime import datetime as _dt, timezone as _tz

    try:
        dt = _dt.fromisoformat(estimated_ready_for_pickup_at.replace("Z", "+00:00"))
        dt_utc = dt.astimezone(_tz.utc)
        iso_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        naive_utc = dt_utc.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        frappe.throw(
            f"Invalid datetime format '{estimated_ready_for_pickup_at}'. "
            "Use ISO 8601, e.g. '2026-02-22T15:00:00Z' or '2026-02-22T10:00:00-05:00'."
        )

    channel_order_name = frappe.db.get_value("Channel Order", {"order_id": order_id}, "name")
    if not channel_order_name:
        frappe.throw(f"No Channel Order found for order_id '{order_id}'")

    frappe.db.set_value("Channel Order", channel_order_name, "estimated_ready_for_pickup_at", naive_utc)
    frappe.db.commit()

    return {
        "status": "updated",
        "order_id": order_id,
        "channel_order": channel_order_name,
        "estimated_ready_for_pickup_at": iso_utc,
    }


@frappe.whitelist()
def update_uber_eats_order_status(order_id, status):
    """Update restaurant delivery status on Uber Eats.

    Use this to mark an order as ready for pickup by the courier.

    Args:
        order_id: Uber Eats order UUID
        status: One of PREPARING, READY_FOR_PICKUP, PICKED_UP
    """
    if not order_id:
        frappe.throw("order_id is required")
    if not status:
        frappe.throw("status is required")

    from .uber_eats_api import update_delivery_status

    update_delivery_status(order_id, status=status)
    return {"status": status, "order_id": order_id}
