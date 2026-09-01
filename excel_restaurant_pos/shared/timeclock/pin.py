"""PIN handling for ArcPOS Employee timeclock authentication."""

from __future__ import annotations

import hashlib
import hmac
import re

import frappe
from frappe import _
from frappe.utils.password import get_encryption_key

PIN_LENGTH = 6
_PIN_PATTERN = re.compile(rf"^\d{{{PIN_LENGTH}}}$")


def normalize_pin(pin) -> str:
	"""Return a validated 6-digit PIN string."""
	pin = str(pin or "").strip()
	if not _PIN_PATTERN.match(pin):
		frappe.throw(_("PIN must be exactly {0} digits").format(PIN_LENGTH), frappe.ValidationError)
	return pin


def hash_pin(pin: str) -> str:
	"""Hash a PIN with the site encryption key.

	Keyed hashing (rather than a per-row salt) keeps the digest deterministic so a
	PIN entered on the POS numpad can be looked up directly, while the plain PIN is
	never stored and the digest is useless without the site key.
	"""
	key = get_encryption_key()
	if isinstance(key, str):
		key = key.encode()
	return hmac.new(key, str(pin).encode(), hashlib.sha256).hexdigest()


def is_hashed_pin(value) -> bool:
	"""True if the value already looks like a stored PIN digest."""
	value = str(value or "")
	return len(value) == 64 and all(char in "0123456789abcdef" for char in value)
