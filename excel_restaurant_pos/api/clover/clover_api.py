"""Clover REST API client.

Handles OAuth token storage/retrieval and REST API calls for:
- Merchant info
- Inventory (items, categories, modifiers)
- Orders
- Payments
"""

import requests
import frappe
from frappe import cache

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

ENDPOINTS = {
    "Sandbox": {
        "auth": "https://sandbox.dev.clover.com/oauth/token",
        "api": "https://apisandbox.dev.clover.com",
    },
    "Production": {
        "auth": "https://www.clover.com/oauth/token",
        "api": "https://api.clover.com",
    },
}

CACHE_KEY = "clover_access_token"
TOKEN_TTL = 86400 * 25  # 25 days (Clover tokens are long-lived)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def get_settings():
    """Return Clover Integration single doc, raising if disabled."""
    settings = frappe.get_single("Clover Integration")
    if not settings.enabled:
        frappe.throw("Clover Integration is not enabled")
    return settings


def _base_url(settings=None):
    settings = settings or get_settings()
    env = settings.environment or "Sandbox"
    return ENDPOINTS[env]["api"]


def _auth_url(settings=None):
    settings = settings or get_settings()
    env = settings.environment or "Sandbox"
    return ENDPOINTS[env]["auth"]


# ---------------------------------------------------------------------------
# OAuth — token exchange (called from oauth_callback whitelist)
# ---------------------------------------------------------------------------

def exchange_code_for_token(code, merchant_id_hint=None):
    """Exchange an authorisation code for an access token and persist it.

    Called by the OAuth callback endpoint after Clover redirects back.
    Uses Clover OAuth v2 endpoint (POST JSON) on the API host, which avoids
    connectivity issues with the separate auth host.

    Args:
        code: The one-time authorisation code from Clover
        merchant_id_hint: merchant_id from the callback URL query params (fallback)

    Returns:
        dict with access_token and merchant_id
    """
    settings = frappe.get_single("Clover Integration")
    env = settings.environment or "Sandbox"
    auth_url = ENDPOINTS[env]["auth"]

    payload = {
        "client_id": settings.client_id,
        "client_secret": settings.get_password("client_secret"),
        "code": code,
    }

    print(f"\n\nClover token exchange → GET {auth_url}")
    print(f"  client_id={payload['client_id']}")
    print(f"  code={payload['code']}\n\n")

    response = requests.get(auth_url, params=payload, timeout=30)

    print(f"\n\nClover token exchange ← {response.status_code}: {response.text}\n\n")

    if response.status_code != 200:
        frappe.log_error(
            "Clover OAuth Token Exchange Error",
            f"URL: {auth_url}\nStatus: {response.status_code}\nBody: {response.text}",
        )
        frappe.throw(f"Failed to exchange Clover code for token: {response.status_code} - {response.text}")

    data = response.json()
    access_token = data.get("access_token") or data.get("token_value")
    merchant_id = data.get("merchant_id") or merchant_id_hint

    if not access_token:
        frappe.log_error("Clover OAuth - No Token", str(data))
        frappe.throw("Clover OAuth response did not include an access_token")

    # Persist directly to DB to bypass read_only field restrictions on form save
    frappe.db.set_value("Clover Integration", "Clover Integration", {
        "access_token": access_token,
        "merchant_id": merchant_id or "",
    })
    frappe.db.commit()

    # Warm the cache
    cache().set_value(CACHE_KEY, access_token, expires_in_sec=TOKEN_TTL)

    frappe.logger().info(f"Clover OAuth token stored for merchant {merchant_id}")
    return {"access_token": access_token, "merchant_id": merchant_id}


def clear_token_cache():
    """Remove the cached token, forcing a fresh read from the doctype."""
    cache().delete_value(CACHE_KEY)


def get_access_token():
    """Return a valid Clover access token (from cache or doctype).

    Priority:
    1. Cached token
    2. Manually entered API token (api_token field)
    3. OAuth access token (access_token field)
    """
    cached = cache().get_value(CACHE_KEY)
    if cached:
        return cached

    settings = get_settings()
    token = (
        (settings.get_password("api_token") if settings.api_token else None)
        or (settings.get_password("access_token") if settings.access_token else None)
    )
    if not token:
        frappe.throw("No Clover access token found. Please paste an API Token or connect via OAuth.")

    cache().set_value(CACHE_KEY, token, expires_in_sec=TOKEN_TTL)
    return token


def _api_headers():
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# Merchant
# ---------------------------------------------------------------------------

def get_merchant(merchant_id=None):
    """Fetch merchant details.

    Args:
        merchant_id: Clover merchant ID (defaults to value stored in doctype)
    """
    settings = get_settings()
    mid = merchant_id or settings.merchant_id
    if not mid:
        frappe.throw("No Merchant ID configured in Clover Integration")

    base = _base_url(settings)
    response = requests.get(f"{base}/v3/merchants/{mid}", headers=_api_headers(), timeout=30)

    if response.status_code != 200:
        frappe.log_error("Clover Get Merchant Error", f"{response.status_code}: {response.text}")
        frappe.throw(f"Failed to fetch Clover merchant: {response.status_code}")

    return response.json()


# ---------------------------------------------------------------------------
# Inventory — Items
# ---------------------------------------------------------------------------

def get_items(merchant_id=None, expand="categories,modifierGroups", limit=100, offset=0):
    """List inventory items for the merchant.

    Args:
        merchant_id: Clover merchant ID
        expand: Comma-separated associations to expand
        limit: Max results per page
        offset: Pagination offset

    Returns:
        Response JSON dict (elements key contains the list)
    """
    settings = get_settings()
    mid = merchant_id or settings.merchant_id
    base = _base_url(settings)

    params = {"expand": expand, "limit": limit, "offset": offset}
    response = requests.get(
        f"{base}/v3/merchants/{mid}/items",
        headers=_api_headers(),
        params=params,
        timeout=30,
    )

    if response.status_code != 200:
        frappe.log_error("Clover Get Items Error", f"{response.status_code}: {response.text}")
        frappe.throw(f"Failed to fetch Clover items: {response.status_code}")

    return response.json()


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def get_orders(merchant_id=None, limit=100, offset=0, filter_str=None):
    """List orders for the merchant.

    Args:
        merchant_id: Clover merchant ID
        limit: Max results per page
        offset: Pagination offset
        filter_str: Optional Clover filter query e.g. "state=open"

    Returns:
        Response JSON dict
    """
    settings = get_settings()
    mid = merchant_id or settings.merchant_id
    base = _base_url(settings)

    params = {"limit": limit, "offset": offset, "expand": "lineItems,payments"}
    if filter_str:
        params["filter"] = filter_str

    response = requests.get(
        f"{base}/v3/merchants/{mid}/orders",
        headers=_api_headers(),
        params=params,
        timeout=30,
    )

    if response.status_code != 200:
        frappe.log_error("Clover Get Orders Error", f"{response.status_code}: {response.text}")
        frappe.throw(f"Failed to fetch Clover orders: {response.status_code}")

    return response.json()


def get_order(order_id, merchant_id=None):
    """Fetch a single order by ID.

    Args:
        order_id: Clover order ID
        merchant_id: Clover merchant ID
    """
    settings = get_settings()
    mid = merchant_id or settings.merchant_id
    base = _base_url(settings)

    response = requests.get(
        f"{base}/v3/merchants/{mid}/orders/{order_id}",
        headers=_api_headers(),
        params={"expand": "lineItems,payments,customers"},
        timeout=30,
    )

    if response.status_code != 200:
        frappe.log_error("Clover Get Order Error", f"Order: {order_id}, {response.status_code}: {response.text}")
        frappe.throw(f"Failed to fetch Clover order {order_id}: {response.status_code}")

    return response.json()


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

def get_payments(merchant_id=None, limit=100, offset=0, filter_str=None):
    """List payments for the merchant.

    Args:
        merchant_id: Clover merchant ID
        limit: Max results per page
        offset: Pagination offset
        filter_str: Optional Clover filter query e.g. "result=SUCCESS"

    Returns:
        Response JSON dict (elements key contains the list)
    """
    settings = get_settings()
    mid = merchant_id or settings.merchant_id
    if not mid:
        frappe.throw("No Merchant ID configured in Clover Integration")

    base = _base_url(settings)
    params = {"limit": limit, "offset": offset, "expand": "order,tender", "count": "true"}
    if filter_str:
        params["filter"] = filter_str

    response = requests.get(
        f"{base}/v3/merchants/{mid}/payments",
        headers=_api_headers(),
        params=params,
        timeout=30,
    )

    if response.status_code != 200:
        frappe.log_error("Clover Get Payments Error", f"{response.status_code}: {response.text}")
        frappe.throw(f"Failed to fetch Clover payments: {response.status_code}")

    data = response.json()
    return {
        "elements": data.get("elements", []),
        "total": data.get("total", len(data.get("elements", []))),
        "limit": limit,
        "offset": offset,
        "href": data.get("href", ""),
    }


def get_payment(payment_id, merchant_id=None):
    """Fetch a single payment by ID.

    Args:
        payment_id: Clover payment ID
        merchant_id: Clover merchant ID
    """
    settings = get_settings()
    mid = merchant_id or settings.merchant_id
    base = _base_url(settings)

    response = requests.get(
        f"{base}/v3/merchants/{mid}/payments/{payment_id}",
        headers=_api_headers(),
        timeout=30,
    )

    if response.status_code != 200:
        frappe.log_error("Clover Get Payment Error", f"Payment: {payment_id}, {response.status_code}: {response.text}")
        frappe.throw(f"Failed to fetch Clover payment {payment_id}: {response.status_code}")

    return response.json()
