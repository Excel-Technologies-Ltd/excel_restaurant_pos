"""Uber Eats webhook endpoint and order processing.

Receives webhook events from Uber Eats, creates Channel Orders,
auto-accepts orders, and handles cancellation / store events.
"""

import json
from html import unescape

import requests

import frappe
from frappe.utils import now_datetime
from datetime import datetime as _dt, timezone as _tz

from .uber_eats_api import (
    verify_webhook_signature,
    _api_headers,
)


@frappe.whitelist(allow_guest=True)
def webhook():
    """Receive Uber Eats webhook notifications.

    Supported event types:
    - orders.notification: New order placed
    - orders.scheduled.notification: Scheduled order placed
    - orders.cancel: Order cancelled by customer/Uber
    - store.provisioned: Store linked to this app
    - store.deprovisioned: Store unlinked from this app
    """
    raw_body = frappe.request.get_data()

    print("\n\n order_payload: ", raw_body, "\n\n")

    # Verify signature
    signature = frappe.request.headers.get("X-Uber-Signature", "")
    if not verify_webhook_signature(raw_body, signature):
        frappe.log_error(
            "Uber Eats Webhook - Signature Mismatch",
            f"Received sig: {signature}\n"
            f"Body bytes ({len(raw_body)}): {raw_body[:500]}"
        )
        frappe.throw("Invalid signature", frappe.AuthenticationError)

    # Parse the event
    try:
        data = json.loads(raw_body)
    except Exception:
        frappe.log_error("Uber Eats Webhook", "Failed to parse JSON body")
        frappe.throw("Invalid JSON body")

    event_type = data.get("event_type")
    event_id = data.get("event_id")
    resource_href = data.get("resource_href", "")
    print("\n\n resource_href :",resource_href, "\n\n")

    frappe.logger().info(f"Uber Eats webhook received: {event_type} ({event_id})")

    meta = data.get("meta", {})
    order_id = meta.get("resource_id")
    store_id = meta.get("user_id")

    if event_type in ("orders.notification", "orders.scheduled.notification"):
        print("\n\n Order is Created \n\n")
        _handle_order_notification(event_type, event_id, order_id, resource_href)

    elif event_type == "orders.cancel":
        _handle_order_cancel(order_id)

    elif event_type == "store.provisioned":
        frappe.logger().info(
            f"Uber Eats store provisioned: store={store_id}"
        )

    elif event_type == "eats.report.success":
        _handle_report_success(data)

    elif event_type == "store.deprovisioned":
        frappe.log_error(
            "Uber Eats Store Deprovisioned",
            f"Store {store_id} was disconnected from this app",
        )

    else:
        frappe.logger().info(f"Uber Eats webhook event '{event_type}' not handled")

    return {"status": "received"}


def _handle_order_notification(event_type, event_id, order_id, resource_href):
    """Handle orders.notification and orders.scheduled.notification.

    Workflow:
    1. Fetch full order details and create Channel Order
    2. Notify staff with the Channel Order ID so the notification links directly to it
    """
    if not order_id:
        frappe.log_error("Uber Eats Webhook", "Missing resource_id in webhook")
        return

    # Idempotency — skip if already processed
    if frappe.db.exists("Channel Order", {"order_id": order_id}):
        frappe.logger().info(f"Duplicate webhook event {event_id} for order {order_id}, skipping")
        return

    is_scheduled = event_type == "orders.scheduled.notification"

    # Fetch full order details, create Channel Order, then notify staff with the doc ID
    frappe.enqueue(
        "excel_restaurant_pos.api.uber_eats.uber_eats.process_uber_eats_order",
        queue="default",
        resource_href=resource_href,
        order_id=order_id,
        event_id=event_id,
        is_scheduled=is_scheduled,
    )


def _handle_order_cancel(order_id):
    """Handle orders.cancel - customer or Uber cancelled the order."""
    if not order_id:
        frappe.log_error("Uber Eats Webhook", "Missing resource_id in cancel event")
        return

    frappe.enqueue(
        "excel_restaurant_pos.api.uber_eats.uber_eats._process_order_cancel",
        queue="default",
        order_id=order_id,
    )


def _process_order_cancel(order_id):
    """Background job: Mark the Channel Order as cancelled when Uber cancels."""
    try:
        channel_order_name = frappe.db.get_value(
            "Channel Order",
            {"order_id": order_id},
            "name",
        )

        if not channel_order_name:
            frappe.logger().info(
                f"Uber Eats cancel event for order {order_id} - no matching Channel Order found"
            )
            return

        frappe.db.set_value(
            "Channel Order", channel_order_name, "current_state", "CANCELLED"
        )
        frappe.db.commit()
        frappe.logger().info(
            f"Uber Eats order {order_id} cancelled -> Channel Order {channel_order_name}"
        )

    except Exception as e:
        frappe.log_error(
            "Uber Eats Cancel Processing Error",
            f"Order {order_id}: {e}",
        )


def _handle_report_success(data):
    """Handle eats.report.success - report is ready for download."""
    report_type = data.get("report_type", "")
    workflow_id = data.get("job_id", "") or data.get("workflow_id", "")
    metadata = data.get("report_metadata", {})
    sections = metadata.get("sections", [])

    download_urls = []
    for section in sections:
        url = section.get("download_url", "")
        if url:
            download_urls.append(unescape(url))

    frappe.logger().info(
        f"Uber Eats report ready: type={report_type}, "
        f"workflow={workflow_id}, downloads={len(download_urls)}"
    )

    doc = frappe.new_doc("Comment")
    doc.comment_type = "Info"
    doc.reference_doctype = "ArcPOS Settings"
    doc.reference_name = "ArcPOS Settings"
    doc.content = json.dumps({
        "event": "eats.report.success",
        "report_type": report_type,
        "workflow_id": workflow_id,
        "download_urls": download_urls,
        "raw": data,
    })
    doc.save(ignore_permissions=True)
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Step 1 — Notify staff immediately on webhook receipt
# ---------------------------------------------------------------------------

def _notify_staff_new_order(order_id, is_scheduled=False, channel_order_name=None):
    """Background job: Send push and Notification Log to restaurant staff.

    Called from process_uber_eats_order after the Channel Order is saved so
    that channel_order_name is available for direct redirect from the notification.

    Args:
        order_id: Uber Eats order UUID
        is_scheduled: True if this is a scheduled order
        channel_order_name: Saved Channel Order document name (for redirect link)
    """
    try:
        roles = ["ArcPOS Channel User"]

        # Use get_all to safely query Has Role child table (column is 'parent', not 'user')
        user_emails = list(set(frappe.get_all(
            "Has Role",
            filters={
                "role": ["in", roles],
                "parenttype": "User",
                "parent": ["not in", ["Administrator", "Guest"]],
            },
            pluck="parent",
        )))

        if not user_emails:
            frappe.logger().info(
                f"No users found for roles {roles} — skipping new order notification"
            )
            return

        order_label = "Scheduled Uber Eats Order" if is_scheduled else "New Uber Eats Order"
        title = f"{order_label} Received" + (f" : {channel_order_name}" if channel_order_name else "")
        body = f"A new order has been received via Uber Eats.\nOrder ID: {order_id}"

        # 1. Create Notification Log for each user
        for user_email in user_emails:
            try:
                log = {
                    "doctype": "Notification Log",
                    "for_user": user_email,
                    "from_user": "Administrator",
                    "subject": title,
                    "email_content": body,
                    "type": "Alert",
                    "read": 0,
                }
                if channel_order_name:
                    log["document_type"] = "Channel Order"
                    log["document_name"] = channel_order_name
                frappe.get_doc(log).insert(ignore_permissions=True)
            except Exception as e:
                frappe.log_error(
                    f"Error creating Notification Log for {user_email}: {e}",
                    "Uber Eats - Notification Log Error",
                )

            try:
                frappe.publish_realtime(
                    "new_uber_eats_order",
                    message={
                        "title": title,
                        "body": body,
                        "order_id": order_id,
                        "channel_order_name": channel_order_name,
                    },
                    user=user_email,
                )
            except Exception:
                pass  # Realtime is best-effort; don't block on failure

        frappe.db.commit()

        # 3. Send Expo push notifications (if SDK available)
        try:
            from exponent_server_sdk import (
                PushClient, PushMessage, PushServerError,
                PushTicketError, DeviceNotRegisteredError,
            )

            token_docs = frappe.get_all(
                "ArcPOS Notification Token",
                filters={"user": ["in", user_emails]},
                fields=["name", "user"],
            )

            push_messages = []
            for token_doc_ref in token_docs:
                token_doc = frappe.get_doc("ArcPOS Notification Token", token_doc_ref.name)
                for token_row in (token_doc.token_list or []):
                    if token_row.token and PushClient.is_exponent_push_token(token_row.token):
                        push_messages.append(
                            PushMessage(
                                to=token_row.token,
                                title=title,
                                body=body,
                                data={
                                    "order_id": order_id,
                                    "channel_order_name": channel_order_name,
                                    "notification_type": "new_uber_eats_order",
                                    "is_scheduled": is_scheduled,
                                },
                                sound="default",
                                priority="high",
                            )
                        )

            if push_messages:
                push_client = PushClient()
                chunk_size = 100
                for i in range(0, len(push_messages), chunk_size):
                    chunk = push_messages[i:i + chunk_size]
                    try:
                        responses = push_client.publish_multiple(chunk)
                        for response, msg in zip(responses, chunk):
                            try:
                                response.validate_response()
                            except DeviceNotRegisteredError:
                                pass
                            except PushTicketError as exc:
                                frappe.log_error(
                                    f"Push ticket error for token {msg.to}: {exc}",
                                    "Uber Eats - Push Ticket Error",
                                )
                    except PushServerError as exc:
                        frappe.log_error(
                            f"Expo push server error for order {order_id}: {exc}",
                            "Uber Eats - Push Server Error",
                        )

                frappe.logger().info(
                    f"Expo push notifications sent for order {order_id} ({len(push_messages)} token(s))"
                )

        except ImportError:
            frappe.logger().info("Expo SDK not available — skipping push notifications")
        except Exception as e:
            frappe.log_error(
                f"Error sending push notifications for order {order_id}: {e}",
                "Uber Eats - Push Notification Error",
            )

    except Exception as e:
        frappe.log_error(
            f"Error in _notify_staff_new_order for order {order_id}: {e}",
            "Uber Eats - Staff Notification Error",
        )


# ---------------------------------------------------------------------------
# Step 1b — Send template email once the Channel Order doc exists
# ---------------------------------------------------------------------------

def _send_new_order_email(channel_order, order_id, is_scheduled=False):
    """Send the configured email template to restaurant staff.

    Called from process_uber_eats_order after the Channel Order is saved so
    that template variables like {{doc.name}} and {{doc.store_name}} resolve.

    Args:
        channel_order: Saved Channel Order document
        order_id: Uber Eats order UUID (for logging)
        is_scheduled: True if this is a scheduled order
    """
    try:
        settings = frappe.get_single("ArcPOS Settings")
        roles = ["Restaurant Chef", "Restaurant Manager"]

        user_emails = list(set(frappe.get_all(
            "Has Role",
            filters={
                "role": ["in", roles],
                "parenttype": "User",
                "parent": ["not in", ["Administrator", "Guest"]],
            },
            pluck="parent",
        )))

        if not user_emails:
            return

        order_label = "Scheduled Uber Eats Order" if is_scheduled else "New Uber Eats Order"
        title = f"{order_label} Received"

        if settings.online_order_email_template:
            template = frappe.get_doc("Email Template", settings.online_order_email_template)
            template_args = {
                "doc": channel_order,
                "order_id": order_id,
                "is_scheduled": is_scheduled,
                "order_label": order_label,
            }
            email_subject = frappe.render_template(template.subject, template_args)
            email_message = frappe.render_template(
                template.response_html or template.response, template_args
            )
        else:
            email_subject = title
            email_message = (
                f"<p>{order_label} has been received via Uber Eats.</p>"
                f"<p><strong>Order:</strong> {channel_order.name}</p>"
                f"<p><strong>Store:</strong> {channel_order.store_name}</p>"
                f"<p><strong>Order ID:</strong> {order_id}</p>"
            )

        frappe.sendmail(
            recipients=user_emails,
            subject=email_subject,
            message=email_message,
            header=None,
            now=True,
        )
        frappe.logger().info(
            f"New order email sent for {order_id} (Channel Order {channel_order.name}) "
            f"to {len(user_emails)} user(s)"
        )
    except Exception as e:
        frappe.log_error(
            f"Error sending new order email for {order_id}: {e}",
            "Uber Eats - New Order Email Error",
        )


# ---------------------------------------------------------------------------
# Step 2 — Fetch order details and create Channel Order
# ---------------------------------------------------------------------------

def process_uber_eats_order(resource_href, order_id, event_id, is_scheduled=False):
    """Background job: Fetch full order via resource_href, create Channel Order, accept.

    Args:
        resource_href: Direct URL to the order from the webhook payload
        order_id: Uber Eats order UUID
        event_id: Webhook event UUID for idempotency
        is_scheduled: True if this is a scheduled order
    """
    try:
        # Fetch full order details using the resource_href from the webhook
        order = _fetch_order_from_href(resource_href, order_id)

        print("Order Details ", order)

        if not isinstance(order, dict):
            frappe.log_error(
                "Uber Eats Order Processing Error",
                f"Order {order_id}: unexpected response type {type(order).__name__}: {str(order)[:300]}",
            )
            return

        # Create Channel Order record (state stays CREATED until staff acts)
        channel_order = _create_channel_order(order, event_id, is_scheduled=is_scheduled)

        # Notify staff now that we have the Channel Order ID for direct redirect
        _notify_staff_new_order(order_id, is_scheduled, channel_order_name=channel_order.name)

        # Send template email now that the Channel Order doc exists (doc.name, doc.store_name etc.)
        _send_new_order_email(channel_order, order_id, is_scheduled)

        frappe.logger().info(
            f"Uber Eats order {order_id} -> Channel Order {channel_order.name}"
        )

    except Exception as e:
        frappe.log_error(
            "Uber Eats Order Processing Error",
            f"Order {order_id}: {e}",
        )


def _fetch_order_from_href(resource_href, order_id):
    """Fetch full order details using the resource_href from the webhook.

    Uses the exact URL that Uber provides in the webhook payload, which
    avoids environment URL construction issues in sandbox.

    Args:
        resource_href: Full order URL from webhook (e.g. https://api.uber.com/v2/eats/order/{id})
        order_id: Order UUID (used for error logging only)

    Returns:
        Order details dict
    """
    import json as _json

    # In sandbox mode the webhook payload contains production URLs (https://api.uber.com).
    # Swap to the sandbox base so the sandbox token is accepted.
    settings = frappe.get_single("ArcPOS Settings")
    if (settings.uber_eats_environment or "Sandbox") == "Sandbox":
        resource_href = resource_href.replace(
            "https://api.uber.com", "https://test-api.uber.com"
        )

    response = requests.get(resource_href, headers=_api_headers(), timeout=30)

    # frappe.log_error(
    #     "Uber Eats Fetch Order - Debug",
    #     f"Order: {order_id}\nURL: {resource_href}\nStatus: {response.status_code}\n"
    #     f"Content-Type: {response.headers.get('Content-Type', '')}\nBody: {response.text[:500]}",
    # )
    # frappe.db.commit()  # Persist debug log immediately regardless of subsequent outcome

    if response.status_code != 200:
        frappe.log_error(
            "Uber Eats Get Order Error",
            f"Order: {order_id}, URL: {resource_href}, Status: {response.status_code}, Body: {response.text}",
        )
        frappe.throw(
            f"Failed to fetch Uber Eats order {order_id}: {response.status_code} - {response.text}"
        )

    data = response.json()

    # Handle double-encoded JSON string response
    if isinstance(data, str):
        data = _json.loads(data)

    return data


def _create_channel_order(order, event_id, is_scheduled=False):
    """Create a Channel Order record from Uber Eats order data.

    Args:
        order: Full order details dict from Uber Eats API
        event_id: Webhook event ID stored in raw_payload for reference
        is_scheduled: True if this is a scheduled order

    Returns:
        Saved Channel Order document
    """
    import json as _json

    eater = order.get("eater", {}) or {}
    cart = order.get("cart", {}) or {}
    items = cart.get("items", []) or []
    payment = order.get("payment", {}) or {}
    charges = payment.get("charges", {}) or {}
    store = order.get("store", {}) or {}

    # Payment totals — Uber uses minor currency units (cents)
    sub_total_info = charges.get("sub_total", {}) or {}
    total_info = charges.get("total", {}) or {}
    subtotal = int(sub_total_info.get("amount", 0)) / 100.0
    total = int(total_info.get("amount", 0)) / 100.0
    currency = sub_total_info.get("currency_code", "") or total_info.get("currency_code", "")

    # Special instructions from the cart
    special_instructions = cart.get("special_instructions", "") or ""

    # Phone can be a plain string or a dict {"number": "..."} depending on Uber API version
    phone_raw = eater.get("phone", "")
    eater_phone = phone_raw if isinstance(phone_raw, str) else (phone_raw or {}).get("number", "")

    

    co = frappe.new_doc("Channel Order")
    co.order_from = "Uber Eats"
    co.order_id = order.get("id", "")
    co.display_id = order.get("display_id", "")
    co.current_state = order.get("current_state", "CREATED")
    co.order_type = order.get("type", "")
    # Both placed_at and estimated_ready_for_pickup_at are ISO-8601 with timezone.
    # MySQL requires naive UTC strings "YYYY-MM-DD HH:MM:SS".
    placed_at_raw = order.get("placed_at", "")
    try:
        dt = _dt.fromisoformat(placed_at_raw) if placed_at_raw else None
        if dt and dt.tzinfo is not None:
            dt = dt.astimezone(_tz.utc).replace(tzinfo=None)
        co.placed_at = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else now_datetime()
    except Exception:
        co.placed_at = now_datetime()

    est_ready_raw = order.get("estimated_ready_for_pickup_at", "")
    try:
        dt = _dt.fromisoformat(est_ready_raw) if est_ready_raw else None
        if dt and dt.tzinfo is not None:
            dt = dt.astimezone(_tz.utc).replace(tzinfo=None)
        co.estimated_ready_for_pickup_at = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None
    except Exception:
        co.estimated_ready_for_pickup_at = None
    co.store_id = store.get("id", "")
    co.store_name = store.get("name", "")
    co.eater_first_name = eater.get("first_name", "")
    co.eater_last_name = eater.get("last_name", "")
    co.eater_phone = eater_phone
    co.special_instructions = special_instructions
    co.subtotal = subtotal
    co.total = total
    co.currency = currency
    co.raw_payload = _json.dumps({"order": order, "event_id": event_id, "is_scheduled": is_scheduled})

    # Add cart items
    for uber_item in items:
        price_info = uber_item.get("price", {}) or {}
        unit_price_info = price_info.get("unit_price", {}) or {}
        total_price_info = price_info.get("total_price", {}) or {}

        unit_price = int(unit_price_info.get("amount", 0)) / 100.0
        item_total = int(total_price_info.get("amount", 0)) / 100.0

        modifier_parts = []
        for mg in (uber_item.get("selected_modifier_groups") or []):
            for mod in (mg.get("selected_items") or []):
                mod_title = mod.get("title", "")
                mod_qty = mod.get("quantity", 1)
                if mod_title:
                    modifier_parts.append(f"{mod_title} x{mod_qty}")

        co.append("items", {
            "item_id": uber_item.get("id", ""),
            "title": uber_item.get("title", "Uber Eats Item"),
            "quantity": uber_item.get("quantity", 1),
            "unit_price": unit_price,
            "total_price": item_total,
            "modifiers": ", ".join(modifier_parts),
            "special_instructions": uber_item.get("special_instructions", ""),
        })

    co.save(ignore_permissions=True)
    frappe.db.commit()

    return co
