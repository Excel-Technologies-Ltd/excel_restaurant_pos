"""Google Wallet loyalty passes: class, object, Save link, live updates, callbacks."""

from __future__ import annotations

import base64
import json
import re
import time

import frappe
from frappe import _
from frappe.utils import cint, get_url

from excel_restaurant_pos.shared.loyalty.settings import WALLET_PASS, get_programme, get_settings
from excel_restaurant_pos.shared.loyalty.wallet.base import file_content

API = "https://walletobjects.googleapis.com/walletobjects/v1"
SCOPE = "https://www.googleapis.com/auth/wallet_object.issuer"
SAVE_URL = "https://pay.google.com/gp/v/save/{jwt}"
ROOT_KEYS_URL = "https://pay.google.com/gp/m/issuer/keys"
SENDER_ID = "GooglePayPasses"
PROTOCOL = "ECv2SigningOnly"
CALLBACK_METHOD = "api.loyalty.wallet.google_callback"

STATES = {"active": "ACTIVE", "inactive": "INACTIVE", "voided": "INACTIVE", "expired": "EXPIRED"}


class WalletError(Exception):
	pass


def enabled() -> bool:
	settings = get_settings()
	return bool(settings and cint(settings.google_enabled) and settings.google_issuer_id)


def _service_account() -> dict:
	raw = file_content(get_settings().google_service_account_json)
	if not raw:
		raise WalletError(_("Attach the Google Wallet service account key in ArcPOS Loyalty Settings."))
	return json.loads(raw)


_SESSIONS: dict = {}


def _session():
	"""One authorised session per process and key: it refreshes its own OAuth
	token, so a nightly reconcile does not fetch a token for every request."""
	from google.auth.transport.requests import AuthorizedSession
	from google.oauth2 import service_account

	info = _service_account()
	cache_key = (frappe.local.site, info.get("private_key_id"))
	session = _SESSIONS.get(cache_key)
	if not session:
		credentials = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
		session = _SESSIONS[cache_key] = AuthorizedSession(credentials)
	return session


def _slug(text: str) -> str:
	return re.sub(r"[^A-Za-z0-9_.-]", "_", text or "loyalty")[:60]


def class_id(programme) -> str:
	settings = get_settings()
	return f"{settings.google_issuer_id}.{_slug(settings.google_class_suffix or programme.programme_name)}"


def object_id(member_number: str) -> str:
	return f"{get_settings().google_issuer_id}.{_slug(member_number)}"


def _image(url):
	return {"sourceUri": {"uri": url}} if url and url.startswith("https://") else None


def build_class(programme, view) -> dict:
	settings = get_settings()
	callback = get_url(f"/api/method/{CALLBACK_METHOD}")
	secret = settings.get_password("google_callback_secret", raise_exception=False)
	if secret:
		callback += f"?token={secret}"
	body = {
		"id": class_id(programme),
		"issuerName": (settings.programme_display_name or programme.programme_name)[:20],
		"programName": view.programme_name or programme.programme_name,
		"hexBackgroundColor": view.background_color,
		"localizedRewardsTier": {"defaultValue": {"language": "en-US", "value": "Tier"}},
		"callbackOptions": {"url": callback},
		"multipleDevicesAndHoldersAllowedStatus": "ONE_USER_ALL_DEVICES",
	}
	logo = _image(view.logo_url)
	if logo:
		body["programLogo"] = logo
	return body


def build_object(view) -> dict:
	text = [
		{"id": "tier", "header": "Tier", "body": view.tier or "-"},
		{"id": "pending", "header": "Pending", "body": str(view.pending)},
	]
	if view.next_expiry_date:
		text.append({"id": "expiry", "header": "Expiring", "body": f"{view.next_expiry_points} on {view.next_expiry_date}"})
	if view.tier_benefits:
		text.append({"id": "benefits", "header": "Benefits", "body": view.tier_benefits[:500]})
	if view.terms:
		text.append({"id": "terms", "header": "Terms", "body": view.terms[:1000]})

	return {
		"id": object_id(view.member_number),
		"classId": class_id(get_programme(view.programme)),
		"state": STATES.get(view.state, "ACTIVE"),
		"accountId": view.member_number,
		"accountName": view.customer_name or view.member_number,
		"loyaltyPoints": {"label": "Points", "balance": {"int": view.balance}},
		"secondaryLoyaltyPoints": {
			"label": "Value",
			"balance": {"money": {"currencyCode": view.currency or "USD", "micros": int(round(view.value * 1_000_000))}},
		},
		"barcode": {"type": "QR_CODE", "value": view.token, "alternateText": view.member_number},
		"textModulesData": text,
		"hexBackgroundColor": view.background_color,
	}


def _request(method: str, path: str, body=None):
	response = _session().request(method, f"{API}/{path}", json=body, timeout=20)
	if response.status_code == 404:
		return None
	if response.status_code >= 400:
		raise WalletError(f"Google Wallet {method} {path}: {response.status_code} {response.text[:500]}")
	return response.json() if response.content else {}


def ensure_class(programme, view, patch: bool = False):
	"""Create the class when missing; patch it only when asked (branding or
	programme changes), not on every pass push -- each patch is a write
	against a reviewed class, and the GET alone doubled every push."""
	body = build_class(programme, view)
	known = f"loyalty:google:class:{body['id']}"
	if not patch and frappe.cache().get_value(known):
		return
	if _request("GET", f"loyaltyClass/{body['id']}") is None:
		_request("POST", "loyaltyClass", {**body, "reviewStatus": "UNDER_REVIEW"})
	elif patch:
		_request("PATCH", f"loyaltyClass/{body['id']}", body)
	frappe.cache().set_value(known, 1, expires_in_sec=86400)


def upsert_object(view):
	ensure_class(get_programme(view.programme), view)
	body = build_object(view)
	if _request("GET", f"loyaltyObject/{body['id']}") is None:
		_request("POST", "loyaltyObject", body)
	else:
		_request("PATCH", f"loyaltyObject/{body['id']}", body)
	return body


def save_url(view, origins: list[str] | None = None) -> str:
	"""A signed 'Add to Google Wallet' link.

	The object is written through the API first and the JWT names only its id:
	a JWT carrying the whole object (terms, benefits, barcode) runs past the
	length Google accepts for a Save link.
	"""
	import jwt

	body = upsert_object(view)
	account = _service_account()
	settings = get_settings()
	origins = origins or [o.strip() for o in (settings.google_origins or "").splitlines() if o.strip()]
	claims = {
		"iss": account["client_email"],
		"aud": "google",
		"typ": "savetowallet",
		"iat": int(time.time()),
		"origins": origins,
		"payload": {"loyaltyObjects": [{"id": body["id"], "classId": body["classId"]}]},
	}
	token = jwt.encode(claims, account["private_key"], algorithm="RS256", headers={"kid": account.get("private_key_id")})
	return SAVE_URL.format(jwt=token)


def update(pass_doc, view):
	"""Patch the object; Google pushes the change to the member's devices.

	A 404 means the member has not tapped Save yet. That is not an error: the
	Save link carries the current object whenever they do.
	"""
	ensure_class(get_programme(view.programme), view)
	_request("PATCH", f"loyaltyObject/{pass_doc.object_id}", build_object(view))


def void(pass_doc, view):
	body = build_object(view)
	body["state"] = "INACTIVE"
	_request("PATCH", f"loyaltyObject/{pass_doc.object_id}", body)


def add_message(pass_doc, header: str, body: str):
	message = {
		"message": {
			"header": header[:100],
			"body": body[:500],
			"id": frappe.generate_hash(length=12),
			"messageType": "TEXT_AND_NOTIFY",
		}
	}
	_request("POST", f"loyaltyObject/{pass_doc.object_id}/addMessage", message)


# ---------------------------------------------------------------- callbacks


def length_value(*parts: bytes) -> bytes:
	"""Tink's toLengthValue: each part prefixed by its 4-byte little-endian length."""
	return b"".join(len(part).to_bytes(4, "little") + part for part in parts)


def _root_keys() -> list[str]:
	cached = frappe.cache().get_value("loyalty:google:root-keys")
	if cached:
		return cached
	import requests

	keys = requests.get(ROOT_KEYS_URL, timeout=10).json().get("keys") or []
	now_ms = int(time.time() * 1000)
	valid = [
		k["keyValue"]
		for k in keys
		if k.get("protocolVersion") == PROTOCOL and int(k.get("keyExpiration") or now_ms + 1) > now_ms
	]
	frappe.cache().set_value("loyalty:google:root-keys", valid, expires_in_sec=6 * 3600)
	return valid


def _verify(public_key_b64: str, signature_b64: str, data: bytes) -> bool:
	from cryptography.exceptions import InvalidSignature
	from cryptography.hazmat.primitives import hashes
	from cryptography.hazmat.primitives.asymmetric import ec
	from cryptography.hazmat.primitives.serialization import load_der_public_key

	try:
		key = load_der_public_key(base64.b64decode(public_key_b64))
		key.verify(base64.b64decode(signature_b64), data, ec.ECDSA(hashes.SHA256()))
		return True
	except (InvalidSignature, ValueError, TypeError):
		return False


def verify_callback(payload: dict, root_keys: list[str] | None = None) -> dict:
	"""Verify a Google Wallet callback (ECv2SigningOnly) and return its signed message."""
	if payload.get("protocolVersion") != PROTOCOL:
		raise WalletError("Unsupported callback protocol")
	issuer = str(get_settings().google_issuer_id)
	intermediate = payload.get("intermediateSigningKey") or {}
	signed_key = intermediate.get("signedKey") or ""
	roots = root_keys if root_keys is not None else _root_keys()

	key_data = length_value(SENDER_ID.encode(), PROTOCOL.encode(), signed_key.encode())
	if not any(_verify(root, sig, key_data) for root in roots for sig in intermediate.get("signatures") or []):
		raise WalletError("Intermediate signing key not signed by Google")

	key = json.loads(signed_key)
	if int(key.get("keyExpiration") or 0) < int(time.time() * 1000):
		raise WalletError("Intermediate signing key expired")

	signed_message = payload.get("signedMessage") or ""
	message_data = length_value(SENDER_ID.encode(), issuer.encode(), PROTOCOL.encode(), signed_message.encode())
	if not _verify(key["keyValue"], payload.get("signature") or "", message_data):
		raise WalletError("Callback signature invalid")

	message = json.loads(signed_message)
	if int(message.get("expTimeMillis") or 0) < int(time.time() * 1000):
		raise WalletError("Callback expired")
	return message


def handle_callback(payload: dict) -> dict:
	message = verify_callback(payload)
	nonce = message.get("nonce")
	if nonce:
		key = f"loyalty:google:nonce:{nonce}"
		if frappe.cache().get_value(key):
			return {"duplicate": True}
		frappe.cache().set_value(key, 1, expires_in_sec=86400)

	name = frappe.db.get_value(WALLET_PASS, {"object_id": message.get("objectId"), "platform": "Google"}, "name")
	if not name:
		return {"unknown_object": True}
	status = {"save": "Installed", "del": "Removed"}.get(message.get("eventType"))
	if status and frappe.db.get_value(WALLET_PASS, name, "status") != "Voided":
		frappe.db.set_value(WALLET_PASS, name, "status", status)
	return {"pass": name, "status": status}
