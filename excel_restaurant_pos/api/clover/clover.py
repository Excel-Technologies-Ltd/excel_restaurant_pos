"""Clover OAuth callback and webhook endpoint.

OAuth flow:
  1. User clicks "Connect with Clover" in Clover Integration doctype
  2. Browser opens Clover /oauth/authorize
  3. Clover redirects to /api/method/...clover.oauth_callback?code=XXX&merchant_id=YYY
  4. oauth_callback exchanges the code for a token via clover_api
  5. Token + merchant_id are stored in the Clover Integration single doc

Webhook:
  Clover POSTs order/payment events to /api/method/...clover.webhook
"""

import json

import frappe

from .clover_api import exchange_code_for_token, get_settings, get_payments, get_payment


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def oauth_callback():
    """Handle the Clover OAuth redirect.

    Clover appends ?code=XXX&merchant_id=YYY to the redirect_uri.
    This endpoint exchanges the code for an access token and stores it.
    """
    code = frappe.request.args.get("code")
    merchant_id = frappe.request.args.get("merchant_id")
    error = frappe.request.args.get("error")

    print(f"\n\nClover OAuth callback: code={code}, merchant_id={merchant_id}, error={error}\n\n")

    if error:
        frappe.log_error("Clover OAuth Error", f"error={error}")
        frappe.respond_as_web_page(
            "Clover OAuth Error",
            f"<h2>Clover OAuth Error: {frappe.utils.escape_html(error)}</h2>",
            http_status_code=400,
            indicator_color="red",
        )
        return

    if not code:
        frappe.throw("Missing authorisation code in Clover callback", frappe.ValidationError)

    # Validate the client_id in the callback matches what's stored in the doctype
    callback_client_id = frappe.request.args.get("client_id")
    if callback_client_id:
        settings = frappe.get_single("Clover Integration")
        if settings.client_id != callback_client_id:
            frappe.log_error(
                "Clover OAuth Client ID Mismatch",
                f"Callback client_id={callback_client_id}, doctype client_id={settings.client_id}"
            )
            frappe.throw(
                f"OAuth client ID mismatch: callback used app <b>{callback_client_id}</b> "
                f"but Clover Integration has <b>{settings.client_id}</b>. "
                f"Update the Client ID in Clover Integration to <b>{callback_client_id}</b> and try again.",
                frappe.ValidationError
            )

    result = exchange_code_for_token(code, merchant_id_hint=merchant_id)
    mid = result.get("merchant_id", merchant_id or "")

    frappe.respond_as_web_page(
        "Clover Connected",
        f"""
        <div style="font-family:sans-serif;text-align:center;padding:60px">
          <h2 style="color:#00A300">&#10003; Clover Connected Successfully</h2>
          <p>Merchant ID: <strong>{mid}</strong></p>
          <p>You can close this tab and return to ArcPOS.</p>
        </div>
        <script>
          if (window.opener) {{
            window.opener.location.reload();
          }}
          setTimeout(() => window.close(), 3000);
        </script>
        """,
        http_status_code=200,
        indicator_color="green",
    )


@frappe.whitelist()
def disconnect():
    """Clear stored Clover token and merchant ID."""
    from .clover_api import clear_token_cache

    settings = frappe.get_single("Clover Integration")
    settings.access_token = ""
    settings.merchant_id = ""
    settings.token_expiry = None
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    clear_token_cache()
    return {"status": "disconnected"}


@frappe.whitelist()
def clear_cache():
    """Clear the cached Clover access token (forces re-read from DB on next request)."""
    from .clover_api import clear_token_cache
    clear_token_cache()
    return {"status": "cache cleared"}


@frappe.whitelist(allow_guest=True)
def test_connection():
    """Verify the stored token works by fetching merchant info."""
    from .clover_api import get_merchant

    settings = get_settings()
    merchant = get_merchant(settings.merchant_id)
    return {
        "merchant_id": merchant.get("id"),
        "merchant_name": merchant.get("name"),
    }


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_payments(limit=100, offset=0, filter_str=None):
    """List payments for the configured merchant.

    Query params:
        limit   – max results (default 100)
        offset  – pagination offset (default 0)
        filter_str – optional Clover filter e.g. "result=SUCCESS"
    """
    settings = get_settings()
    data = get_payments(
        merchant_id=settings.merchant_id,
        limit=int(limit),
        offset=int(offset),
        filter_str=filter_str,
    )
    return data


@frappe.whitelist()
def get_payment_detail(payment_id):
    """Fetch a single payment by its Clover payment ID."""
    settings = get_settings()
    return get_payment(payment_id, merchant_id=settings.merchant_id)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@frappe.whitelist()
def sync_payments():
    """Manually trigger a full Clover payment sync (same job as the nightly cron)."""
    from .clover_sync import sync_clover_payments
    result = sync_clover_payments()
    return result


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def webhook():
    """Receive Clover webhook notifications.

    Clover sends a POST with a JSON body. The structure varies by event type.
    Register this URL in your Clover Developer Dashboard under App Settings > Webhooks.

    Supported object types:
    - PAYMENT
    - ORDER
    - ITEM
    """
    raw_body = frappe.request.get_data()

    try:
        data = json.loads(raw_body)
    except Exception:
        frappe.log_error("Clover Webhook - Invalid JSON", str(raw_body[:500]))
        frappe.throw("Invalid JSON body")

    print("\n\nClover Webhook Payload:", data, "\n\n")

    merchant_id = data.get("merchantId") or data.get("merchant_id", "")
    app_id = data.get("appId", "")
    object_type = data.get("type", "")        # e.g. "PAYMENT", "ORDER"
    notifications = data.get("notifications") or []

    frappe.logger().info(
        f"Clover webhook received: type={object_type}, merchant={merchant_id}, "
        f"events={len(notifications)}"
    )

    for notification in notifications:
        event_type = notification.get("type", "")
        object_id = notification.get("objectId", "")

        if object_type == "ORDER":
            _handle_order_event(event_type, object_id, merchant_id)
        elif object_type == "PAYMENT":
            _handle_payment_event(event_type, object_id, merchant_id)
        else:
            frappe.logger().info(
                f"Clover webhook: unhandled object_type={object_type}, event={event_type}"
            )

    return {"status": "received"}


def _handle_order_event(event_type, order_id, merchant_id):
    """Route an ORDER notification to the appropriate handler."""
    if not order_id:
        return

    if event_type == "CREATE":
        frappe.enqueue(
            "excel_restaurant_pos.api.clover.clover.process_clover_order",
            queue="default",
            order_id=order_id,
            merchant_id=merchant_id,
        )
    elif event_type == "DELETE":
        frappe.enqueue(
            "excel_restaurant_pos.api.clover.clover._process_order_cancel",
            queue="default",
            order_id=order_id,
        )
    else:
        frappe.logger().info(f"Clover ORDER event '{event_type}' for {order_id} — not handled")


def _handle_payment_event(event_type, payment_id, merchant_id):
    """Handle PAYMENT notifications (for future use)."""
    frappe.logger().info(
        f"Clover PAYMENT event '{event_type}' for payment {payment_id} — merchant {merchant_id}"
    )


# ---------------------------------------------------------------------------
# Order processing (background job)
# ---------------------------------------------------------------------------

def process_clover_order(order_id, merchant_id=None):
    """Background job: fetch full order from Clover and create Channel Order."""
    try:
        from .clover_api import get_order

        # Idempotency check
        if frappe.db.exists("Channel Order", {"order_id": order_id}):
            frappe.logger().info(f"Clover order {order_id} already processed — skipping")
            return

        order = get_order(order_id, merchant_id)
        channel_order = _create_channel_order(order)

        frappe.logger().info(
            f"Clover order {order_id} -> Channel Order {channel_order.name}"
        )

    except Exception as e:
        frappe.log_error(
            "Clover Order Processing Error",
            f"Order {order_id}: {e}",
        )


def _process_order_cancel(order_id):
    """Background job: mark Channel Order as cancelled."""
    try:
        name = frappe.db.get_value("Channel Order", {"order_id": order_id}, "name")
        if not name:
            frappe.logger().info(f"Clover cancel: no Channel Order found for {order_id}")
            return

        frappe.db.set_value("Channel Order", name, "current_state", "CANCELLED")
        frappe.db.commit()
        frappe.logger().info(f"Clover order {order_id} cancelled -> Channel Order {name}")

    except Exception as e:
        frappe.log_error("Clover Cancel Processing Error", f"Order {order_id}: {e}")


def _create_channel_order(order):
    """Create a Channel Order from a Clover order dict.

    Args:
        order: Full order dict from Clover API

    Returns:
        Saved Channel Order document
    """
    line_items_data = (order.get("lineItems") or {}).get("elements") or []
    payments_data = (order.get("payments") or {}).get("elements") or []
    customers_data = (order.get("customers") or {}).get("elements") or []

    # Clover stores amounts in cents
    total_cents = order.get("total", 0) or 0
    total = total_cents / 100.0

    customer = customers_data[0] if customers_data else {}
    customer_name_parts = [
        customer.get("firstName", ""),
        customer.get("lastName", ""),
    ]

    co = frappe.new_doc("Channel Order")
    co.order_from = "Clover"
    co.order_id = order.get("id", "")
    co.display_id = order.get("id", "")
    co.current_state = "CREATED"
    co.order_type = order.get("orderType", {}).get("label", "") if order.get("orderType") else ""
    co.placed_at = frappe.utils.now_datetime()
    co.eater_first_name = customer.get("firstName", "")
    co.eater_last_name = customer.get("lastName", "")
    co.eater_phone = (customer.get("phoneNumbers") or {}).get("elements", [{}])[0].get("phoneNumber", "") if customer else ""
    co.total = total
    co.subtotal = total
    co.raw_payload = frappe.as_json(order)

    for item in line_items_data:
        price_cents = item.get("price", 0) or 0
        unit_price = price_cents / 100.0
        qty = item.get("qty", 1) or 1

        # Collect modifier names
        modifier_parts = []
        for mod in ((item.get("modifications") or {}).get("elements") or []):
            mod_name = mod.get("name", "")
            if mod_name:
                modifier_parts.append(mod_name)

        co.append("items", {
            "item_id": item.get("id", ""),
            "title": item.get("name", "Clover Item"),
            "quantity": qty,
            "unit_price": unit_price,
            "total_price": unit_price * qty,
            "modifiers": ", ".join(modifier_parts),
            "special_instructions": item.get("note", ""),
        })

    co.save(ignore_permissions=True)
    frappe.db.commit()

    return co
