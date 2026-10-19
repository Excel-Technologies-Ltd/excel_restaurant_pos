"""Step-up verification for large staff redemptions at the POS.

Above `step_up_threshold_points` a cashier must enter a 6-digit code sent to
the member. Codes live in Redis, hashed, for 5 minutes. The proof of a
verified code also lives in Redis -- never on the invoice, which the POS can
write -- so a client cannot mark its own order verified.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import frappe
from frappe import _
from frappe.utils import cint

from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, get_settings

CODE_TTL = 300
VERIFIED_TTL = 2 * 3600
MAX_SENDS, SEND_WINDOW = 3, 600
MAX_ATTEMPTS = 5


def _code_key(account, invoice):
	return f"loyalty:otp:{account}:{invoice}"


def _verified_key(account, invoice):
	return f"loyalty:otp-ok:{account}:{invoice}"


def _tries_key(account, invoice):
	return f"loyalty:otp-tries:{account}:{invoice}"


def _count(key: str, window: int) -> int:
	"""Atomically add one to a counter that lives for `window` seconds from its
	first use. A read-then-write counter lets parallel requests all read the
	same value and slip past the limit together."""
	cache = frappe.cache()
	redis_key = cache.make_key(key)
	cache.set(redis_key, 0, ex=window, nx=True)
	return cint(cache.incr(redis_key))


def _hash(code: str, invoice: str) -> str:
	return hashlib.sha256(f"{invoice}:{code}".encode()).hexdigest()


def threshold() -> int:
	settings = get_settings()
	return cint(settings.step_up_threshold_points) if settings else 0


def required(points: int) -> bool:
	limit = threshold()
	return bool(limit and cint(points) > limit)


def assert_step_up(account: str, doc, points: int):
	"""Refuse a staff redemption above the threshold without a verified code."""
	if not required(points):
		return
	from excel_restaurant_pos.shared.customer_access import is_staff

	# The member's own storefront session is already strong authentication.
	if not is_staff():
		return
	if cint(frappe.cache().get_value(_verified_key(account, doc.name))) >= cint(points):
		return
	frappe.throw(
		_("Redeeming more than {0} points needs the verification code sent to the member.").format(threshold()),
		title=_("Verification Required"),
	)


def request(account: str, invoice: str, points: int) -> dict:
	"""A code for `points` on `invoice`. The amount is fixed here and shown to
	the member, so the cashier cannot verify one figure and redeem another."""
	if cint(points) <= 0:
		frappe.throw(_("Enter the points to be verified."))
	if _count(f"loyalty:otp-sends:{account}", SEND_WINDOW) > MAX_SENDS:
		frappe.throw(_("Too many codes requested. Please wait a few minutes."))

	cache = frappe.cache()
	code = f"{secrets.randbelow(10**6):06d}"
	cache.delete_value(_tries_key(account, invoice))
	cache.set_value(
		_code_key(account, invoice),
		{"hash": _hash(code, invoice), "points": cint(points)},
		expires_in_sec=CODE_TTL,
	)

	from excel_restaurant_pos.shared.loyalty.notifications import send_code

	return {"sent_to": send_code(account, code, cint(points)), "expires_in": CODE_TTL, "points": cint(points)}


def verify(account: str, invoice: str, code: str, points: int | None = None) -> bool:
	cache = frappe.cache()
	key = _code_key(account, invoice)
	stored = cache.get_value(key)
	if not stored:
		frappe.throw(_("The code has expired. Request a new one."))

	# Counted before the comparison, so parallel guesses each use up a try.
	if _count(_tries_key(account, invoice), CODE_TTL) > MAX_ATTEMPTS:
		cache.delete_value(key)
		frappe.throw(_("Too many wrong codes. Request a new one."))

	if not hmac.compare_digest(stored.get("hash") or "", _hash((code or "").strip(), invoice)):
		return False

	approved = cint(stored.get("points"))
	if points and cint(points) != approved:
		frappe.throw(_("This code was sent for {0} points. Request a new code for a different amount.").format(approved))
	points = approved

	cache.delete_value([key, _tries_key(account, invoice)])
	cache.set_value(_verified_key(account, invoice), cint(points), expires_in_sec=VERIFIED_TTL)
	if frappe.get_meta("Sales Invoice").has_field("custom_loyalty_verified"):
		frappe.db.set_value("Sales Invoice", invoice, "custom_loyalty_verified", 1, update_modified=False)
	frappe.get_doc(ACCOUNT, account).add_comment(
		"Info", _("Step-up code verified for {0} points on {1}.").format(cint(points), invoice)
	)
	return True
