import frappe
from frappe import _


def rate_limit_guest(endpoint, limit=5, seconds=60):
    """
    Apply rate limiting for guest endpoints.

    Args:
        endpoint: The endpoint identifier
        limit: Maximum number of requests allowed
        seconds: Time window in seconds

    Raises:
        frappe.ValidationError: If rate limit is exceeded
    """
    key = f"guest:{endpoint}"
    cache = frappe.cache()

    # Get current count
    current_count = cache.get_value(key) or 0

    if current_count >= limit:
        frappe.throw(
            _("Too many requests. Please try again later."), exc=frappe.ValidationError
        )

    # Increment count and set expiry
    cache.set_value(key, current_count + 1, expires_in_sec=seconds)


def rate_limit_by_caller(endpoint, limit=20, seconds=60):
    """Rate limit a public endpoint per caller.

    Keyed on the logged in user, or the client IP for guests. Unlike
    `rate_limit_guest`, which shares a single counter across everyone calling an
    endpoint, this does not let one caller lock everybody else out.

    Args:
        endpoint: The endpoint identifier
        limit: Maximum number of requests allowed per caller
        seconds: Time window in seconds

    Raises:
        frappe.ValidationError: If rate limit is exceeded
    """
    user = frappe.session.user if frappe.session else "Guest"
    if user and user != "Guest":
        caller = f"user:{user}"
    else:
        caller = f"ip:{getattr(frappe.local, 'request_ip', None) or 'unknown'}"

    key = f"arcpos:rate:{endpoint}:{caller}"
    cache = frappe.cache()

    current_count = cache.get_value(key) or 0
    if current_count >= limit:
        frappe.throw(
            _("Too many requests. Please try again later."), exc=frappe.ValidationError
        )

    cache.set_value(key, current_count + 1, expires_in_sec=seconds)
