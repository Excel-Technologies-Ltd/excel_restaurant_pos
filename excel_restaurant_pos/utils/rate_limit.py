"""Rate limiting helpers for public (guest) API endpoints."""

from functools import wraps

import frappe
from frappe import _

# Default budgets for Guest calls to /api/method/...
# Per-caller (IP for guests), so one attacker cannot lock out everyone.
#
# Frappe frontends usually POST even for reads (frappe.call), so HTTP method
# is a poor write/read signal. Unknown guest methods get the default budget;
# known catalog reads get a higher one; known spam writers get a lower one.
GUEST_API_DEFAULT_LIMIT = 60
GUEST_API_READ_LIMIT = 120
GUEST_API_WRITE_LIMIT = 30  # kept for decorator / callers that opt into "write"
GUEST_API_WINDOW = 60

# Extra flood cap across all guest method calls from one IP.
GUEST_API_GLOBAL_LIMIT = 200
GUEST_API_GLOBAL_WINDOW = 60

# Catalog / settings style reads: higher budget (aliases + full paths).
READ_ALLOWLIST = frozenset(
	{
		"api.items.list",
		"api.items.details",
		"api.items.most_sold",
		"api.item_groups.list",
		"api.menus.list",
		"api.settings.get",
		"api.settings.get_system",
		"api.settings.system_settings",
		"api.territories.default",
		"api.mode_of_payments.list",
		"api.tables.get",
		"api.tips.get",
		"api.arcpos_offers.get_next_available",
		"api.sales_invoices.get",
		"api.feedbacks.get",
		"api.feedbacks.get_by_invoice",
		"api.files.download_public_file",
		"excel_restaurant_pos.api.item.get_item_list.get_item_list",
		"excel_restaurant_pos.api.item.get_item_details.get_item_details",
		"excel_restaurant_pos.api.item_group.get_item_group_list.get_item_group_list",
		"excel_restaurant_pos.api.menu.get_menu_list.get_menu_list",
		"excel_restaurant_pos.api.settings.get_settings.get_settings",
		"excel_restaurant_pos.api.settings.get_system_settings.get_system_settings",
		"excel_restaurant_pos.api.settings.system_settings.system_settings",
		"excel_restaurant_pos.api.territory.get_default_territory.get_default_territory",
		"excel_restaurant_pos.api.mode_of_payment.mode_of_paymet_list.get_mode_of_payment_list",
		"excel_restaurant_pos.api.table.get_table.get_table",
		"excel_restaurant_pos.api.tips.get_tips.get_tips",
		"excel_restaurant_pos.api.arcpos_offers.get_next_available_offers.get_next_available_offers",
		"excel_restaurant_pos.api.sales_invoice.get_sales_invoice.get_sales_invoice",
		"excel_restaurant_pos.api.feedback.get_feedback.get_feedback",
		"excel_restaurant_pos.api.file.download_files.download_public_file",
		"excel_restaurant_pos.api.reservation.create_reservation.get_available_slots",
	}
)

# Known spam / mutation surfaces: tighter than the default budget.
# Keys are the public method path as called in the URL (alias or full path).
STRICT_WRITE_LIMITS = {
	# Website checkout / order spam
	"api.sales_invoices.add": (10, 60),
	"excel_restaurant_pos.api.sales_invoice.add_or_update_invoice.add_or_update_invoice": (
		10,
		60,
	),
	# Table / kitchen orders
	"excel_restaurant_pos.api.item.item.create_order": (10, 60),
	# Reservation form spam: 3 an hour per IP. Nobody books more tables than that.
	"excel_restaurant_pos.api.reservation.create_reservation.create_reservation": (3, 3600),
	# Address / contact writes
	"api.addresses.add": (15, 60),
	"api.addresses.edit": (15, 60),
	"excel_restaurant_pos.api.address.add_customer_address.add_customer_address": (15, 60),
	"excel_restaurant_pos.api.address.edit_customer_address.edit_customer_address": (
		15,
		60,
	),
	# Payment mutations
	"api.payments.get_ticket": (20, 60),
	"api.payments.receipt_payment": (15, 60),
	"api.payments.cancel_payment": (15, 60),
	"excel_restaurant_pos.api.payments.get_payment_ticket.get_payment_ticket": (20, 60),
	"excel_restaurant_pos.api.payments.receipt_payment.receipt_payment": (15, 60),
	"excel_restaurant_pos.api.payments.cancel_payment.cancel_payment": (15, 60),
	# Feedback submit
	"api.feedbacks.update": (10, 60),
	"excel_restaurant_pos.api.feedback.update_feedback.update_feedback": (10, 60),
	# Auth / signup (when guest)
	"excel_restaurant_pos.overrides.user.sign_up": (10, 60),
	"excel_restaurant_pos.overrides.user.verify_otp": (20, 60),
	"excel_restaurant_pos.overrides.user.resend_otp": (5, 60),
	"excel_restaurant_pos.api.auth.login.login": (20, 60),
	"excel_restaurant_pos.api.auth.google.google_login": (20, 60),
	"excel_restaurant_pos.api.auth.login.verify_2fa_and_login": (20, 60),
	# File upload
	"api.files.upload_public_file": (10, 60),
	"excel_restaurant_pos.api.file.upload_files.upload_public_file": (10, 60),
	# Coupon / gift card (also have their own limits; keep aligned)
	"api.coupons.validate": (20, 60),
	"api.gift_cards.verify": (20, 60),
	"api.gift_cards.apply": (20, 60),
	# Unverified DoorDash stub — do not leave unbounded
	"excel_restaurant_pos.api.doordash.doordash.create_order": (10, 60),
}

# Partner webhooks / OAuth redirects with their own verification.
# Do not throttle these with guest form budgets.
EXEMPT_GUEST_METHODS = frozenset(
	{
		"excel_restaurant_pos.api.uber_eats.uber_eats.webhook",
		"api.uber_eats.webhook",
		"excel_restaurant_pos.api.clover.clover.webhook",
		"excel_restaurant_pos.api.clover.clover.oauth_callback",
	}
)


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

	# Get current count. expires=True keeps the miss out of frappe.local:
	# set_value with expires_in_sec never updates that local dict, so a cached
	# miss would freeze the counter for the rest of the process.
	current_count = cache.get_value(key, expires=True) or 0

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

	# expires=True: see rate_limit_guest.
	current_count = cache.get_value(key, expires=True) or 0
	if current_count >= limit:
		frappe.throw(
			_("Too many requests. Please try again later."), exc=frappe.ValidationError
		)

	cache.set_value(key, current_count + 1, expires_in_sec=seconds)


def rate_limit_public(endpoint=None, limit=None, seconds=GUEST_API_WINDOW):
	"""Decorator: throttle a whitelisted guest endpoint per caller.

	Prefer the central `limit_guest_api_requests` before_request hook for
	blanket coverage; use this when an endpoint needs an explicit tighter budget.
	"""

	def decorator(fn):
		endpoint_key = endpoint or fn.__name__
		call_limit = limit if limit is not None else GUEST_API_WRITE_LIMIT

		@wraps(fn)
		def wrapper(*args, **kwargs):
			rate_limit_by_caller(endpoint_key, limit=call_limit, seconds=seconds)
			return fn(*args, **kwargs)

		return wrapper

	return decorator


def _guest_api_method_name():
	"""Resolve the /api/method/... name from the current request."""
	request = getattr(frappe.local, "request", None)
	if not request:
		return ""

	path = (request.path or "").rstrip("/")
	marker = "/api/method/"
	if marker in path:
		return path.split(marker, 1)[1]
	return ""


def _limits_for_method(method_name):
	"""Return (limit, seconds) for a guest API method."""
	if method_name in STRICT_WRITE_LIMITS:
		return STRICT_WRITE_LIMITS[method_name]

	if method_name in READ_ALLOWLIST:
		return GUEST_API_READ_LIMIT, GUEST_API_WINDOW

	return GUEST_API_DEFAULT_LIMIT, GUEST_API_WINDOW


def _ensure_jwt_session_if_present():
	"""Apply Bearer JWT before Guest checks.

	`auth_hooks` run after `before_request` in Frappe, so without this a POS
	client with a valid JWT would still be counted as Guest and share the IP
	budget with storefront traffic.
	"""
	if not frappe.session or frappe.session.user != "Guest":
		return

	auth_header = frappe.get_request_header("Authorization")
	if not auth_header:
		return

	parts = auth_header.split()
	if len(parts) != 2 or parts[0].lower() != "bearer":
		return

	# Reuse the same JWT auth hook used later in the request lifecycle.
	from excel_restaurant_pos.auth import validate as validate_jwt

	validate_jwt()


def _limit_signed_in_customer(method_name):
	"""The strict per-method budgets, for a signed-in customer.

	Ordering, paying and gift cards now need an account, so the guest budgets
	never see those calls -- without this a signed-in customer could place orders
	as fast as they liked. The same limits apply, keyed on the account instead of
	the IP. Staff are exempt: a POS terminal places orders all day.
	"""
	limits = STRICT_WRITE_LIMITS.get(method_name)
	if not limits:
		return

	from excel_restaurant_pos.shared.customer_access import is_staff

	if is_staff(frappe.session.user):
		return

	limit, seconds = limits
	rate_limit_by_caller(f"customer_api:{method_name}", limit=limit, seconds=seconds)


def limit_guest_api_requests():
	"""before_request hook: rate-limit Guest calls to public API methods.

	JWT Bearer tokens are applied first so authenticated POS clients are not
	throttled as Guest. Partner webhooks in EXEMPT_GUEST_METHODS are skipped.
	"""
	request = getattr(frappe.local, "request", None)
	if not request:
		return

	path = request.path or ""
	if "/api/method/" not in path:
		return

	_ensure_jwt_session_if_present()

	method_name = _guest_api_method_name()
	if not method_name or method_name in EXEMPT_GUEST_METHODS:
		return

	if frappe.session and frappe.session.user != "Guest":
		_limit_signed_in_customer(method_name)
		return

	# Global flood budget first (route scanning across many methods).
	rate_limit_by_caller(
		"guest_api:all",
		limit=GUEST_API_GLOBAL_LIMIT,
		seconds=GUEST_API_GLOBAL_WINDOW,
	)

	limit, seconds = _limits_for_method(method_name)
	rate_limit_by_caller(f"guest_api:{method_name}", limit=limit, seconds=seconds)
