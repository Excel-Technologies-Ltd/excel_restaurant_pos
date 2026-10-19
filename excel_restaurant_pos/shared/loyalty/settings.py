"""Loyalty settings, the active programme, and the channel model."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from excel_restaurant_pos.shared.coupon.services import get_coupon_settings, normalize_channel

SETTINGS = "ArcPOS Loyalty Settings"
PROGRAMME = "ArcPOS Loyalty Programme"
ACCOUNT = "ArcPOS Loyalty Account"
TXN = "ArcPOS Loyalty Transaction"
CAMPAIGN = "ArcPOS Loyalty Campaign"
REWARD = "ArcPOS Loyalty Reward"
EVENT_TYPE = "ArcPOS Loyalty Event Type"
SEGMENT = "ArcPOS Loyalty Segment"
ADJUSTMENT = "ArcPOS Loyalty Adjustment"
WALLET_PASS = "ArcPOS Wallet Pass"
DEVICE_REGISTRATION = "ArcPOS Wallet Device Registration"
NOTIFICATION_LOG = "ArcPOS Loyalty Notification Log"
TIER_CHANGE = "ArcPOS Loyalty Tier Change"
LIABILITY_RUN = "ArcPOS Loyalty Liability Run"

LOYALTY_MANAGER = "ArcPOS Loyalty Manager"

# (order_from, service_type) pairs per channel key, the same model the gift
# card settings use. Third-party channels (Uber Eats, DoorDash) match none of
# them, so they neither earn nor redeem.
CHANNELS = {
	"dine_in": {("table", "dine-in"), ("table", "takeout")},
	"in_store_pickup": {("in store", "pickup")},
	"online_delivery": {("website", "delivery")},
	"online_pickup": {("website", "pickup")},
}

# ArcPOS Settings fields holding the walk-in customers orders fall back to.
DEFAULT_CUSTOMER_FIELDS = (
	"customer",
	"default_customer_website",
	"subsite_default_customer",
	"uber_eats_default_customer",
)


def get_settings():
	"""The settings document, or None while the DocType is not installed yet."""
	try:
		return frappe.get_cached_doc(SETTINGS)
	except frappe.DoesNotExistError:
		return None


def is_enabled() -> bool:
	settings = get_settings()
	return bool(settings and cint(settings.enabled))


def programme_is_live(programme, on_date=None) -> bool:
	if not programme or programme.status != "Active":
		return False
	on_date = getdate(on_date or nowdate())
	if programme.start_date and on_date < getdate(programme.start_date):
		return False
	if programme.end_date and on_date > getdate(programme.end_date):
		return False
	return True


def get_programme(name=None):
	"""A programme document (cached), defaulting to the configured one."""
	if not name:
		settings = get_settings()
		name = settings.active_programme if settings else None
	if not name:
		return None
	try:
		return frappe.get_cached_doc(PROGRAMME, name)
	except frappe.DoesNotExistError:
		return None


def get_active_programme(on_date=None):
	"""The programme new activity posts to, when loyalty is on and it is live."""
	if not is_enabled():
		return None
	programme = get_programme()
	return programme if programme_is_live(programme, on_date) else None


def excluded_customers() -> set[str]:
	settings = get_settings()
	excluded = {row.customer for row in (settings.get("excluded_customers") or []) if row.customer} if settings else set()

	arcpos = get_coupon_settings()
	if arcpos:
		excluded |= {arcpos.get(f) for f in DEFAULT_CUSTOMER_FIELDS if arcpos.get(f)}
	return excluded


def is_excluded_customer(customer) -> bool:
	return not customer or customer in excluded_customers()


def channel_key(doc) -> str | None:
	"""The loyalty channel of an order, or None for a channel loyalty ignores."""
	pair = normalize_channel(doc.get("custom_order_from"), doc.get("custom_service_type"))
	for key, pairs in CHANNELS.items():
		if pair in pairs:
			return key
	return None


def channel_allowed(record, prefix: str, key: str | None) -> bool:
	"""Whether `record` has the `{prefix}_{key}` channel flag set."""
	if not key:
		return False
	return bool(cint(record.get(f"{prefix}_{key}")))


def member_token_secret() -> str:
	settings = get_settings()
	secret = settings.get_password("member_token_secret", raise_exception=False) if settings else None
	if not secret:
		frappe.throw(_("Loyalty member token secret is not configured."))
	return secret


def point_value(programme) -> float:
	return flt(programme.point_value) if programme else 0.0
