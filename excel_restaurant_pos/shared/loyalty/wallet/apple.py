"""Apple Wallet loyalty passes: signed .pkpass files and APNs update pushes."""

from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import tempfile
import zipfile

import frappe
from frappe import _
from frappe.utils import cint

from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, DEVICE_REGISTRATION, WALLET_PASS, get_settings
from excel_restaurant_pos.shared.loyalty.wallet.base import file_content
from excel_restaurant_pos.shared.loyalty.wallet.google import WalletError

APNS_HOSTS = {"Production": "api.push.apple.com", "Sandbox": "api.sandbox.push.apple.com"}
PLATFORM = "Apple"


def enabled() -> bool:
	settings = get_settings()
	return bool(settings and cint(settings.apple_enabled) and settings.apple_pass_type_id and settings.apple_team_id)


def hash_token(token: str) -> str:
	return hashlib.sha256((token or "").encode()).hexdigest()


def ensure_pass(account: str):
	"""The account's Apple pass record, created on first download. Its serial is the member number."""
	name = frappe.db.get_value(WALLET_PASS, {"account": account, "platform": PLATFORM}, "name")
	if name:
		return frappe.get_doc(WALLET_PASS, name)
	token = secrets.token_hex(24)
	doc = frappe.get_doc(
		{
			"doctype": WALLET_PASS,
			"account": account,
			"platform": PLATFORM,
			"object_id": frappe.db.get_value(ACCOUNT, account, "member_number") or account,
			"status": "Issued",
			"auth_token": token,
			"auth_token_hash": hash_token(token),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def rgb(hex_color: str) -> str:
	value = (hex_color or "#000000").lstrip("#")
	if len(value) == 3:
		value = "".join(c * 2 for c in value)
	r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
	return f"rgb({r}, {g}, {b})"


def build_pass_json(view, pass_doc, auth_token: str | None = None) -> dict:
	settings = get_settings()
	expiring = f"{view.next_expiry_points} on {view.next_expiry_date}" if view.next_expiry_date else "-"
	back = [{"key": "member", "label": "Member number", "value": view.member_number}]
	if view.tier_benefits:
		back.append({"key": "benefits", "label": "Benefits", "value": view.tier_benefits})
	if view.terms:
		back.append({"key": "terms", "label": "Terms", "value": view.terms})

	body = {
		"formatVersion": 1,
		"passTypeIdentifier": settings.apple_pass_type_id,
		"teamIdentifier": settings.apple_team_id,
		"serialNumber": pass_doc.object_id,
		"organizationName": settings.apple_organization_name or view.programme_name,
		"description": view.programme_name or "Loyalty",
		"logoText": view.programme_name,
		"foregroundColor": rgb(view.foreground_color),
		"backgroundColor": rgb(view.background_color),
		"labelColor": rgb(view.label_color),
		"barcodes": [
			{
				"format": "PKBarcodeFormatQR",
				"message": view.token,
				"messageEncoding": "iso-8859-1",
				"altText": view.member_number,
			}
		],
		"storeCard": {
			"primaryFields": [
				{"key": "points", "label": "POINTS", "value": view.balance, "changeMessage": "You now have %@ points"}
			],
			"secondaryFields": [
				{"key": "value", "label": "VALUE", "value": view.value_text},
				{"key": "tier", "label": "TIER", "value": view.tier or "-", "changeMessage": "Your tier is now %@"},
			],
			"auxiliaryFields": [
				{"key": "expiring", "label": "EXPIRING", "value": expiring, "changeMessage": "Expiring soon: %@"},
				{"key": "pending", "label": "PENDING", "value": view.pending},
			],
			"backFields": back,
		},
		"authenticationToken": auth_token or pass_doc.get_password("auth_token"),
	}
	if settings.apple_web_service_url:
		body["webServiceURL"] = settings.apple_web_service_url.rstrip("/")
	if view.state == "voided":
		body["voided"] = True
	if view.programme_end_date:
		body["expirationDate"] = f"{view.programme_end_date}T23:59:59Z"
	return body


def _images() -> dict[str, bytes]:
	settings = get_settings()
	icon = file_content(settings.pass_icon)
	if not icon:
		raise WalletError(_("Attach a Pass Icon (PNG) in ArcPOS Loyalty Settings; Apple Wallet requires one."))
	images = {"icon.png": icon, "icon@2x.png": icon}
	logo = file_content(settings.pass_logo)
	if logo:
		images.update({"logo.png": logo, "logo@2x.png": logo})
	strip = file_content(settings.pass_strip_image)
	if strip:
		images.update({"strip.png": strip, "strip@2x.png": strip})
	return images


def _signing_material():
	from cryptography import x509
	from cryptography.hazmat.primitives.serialization import pkcs12

	settings = get_settings()
	p12 = file_content(settings.apple_pass_certificate)
	wwdr_raw = file_content(settings.apple_wwdr_certificate)
	if not p12 or not wwdr_raw:
		raise WalletError(_("Attach the Pass Type certificate (.p12) and the Apple WWDR certificate."))
	password = settings.get_password("apple_pass_certificate_password", raise_exception=False)
	key, cert, _extra = pkcs12.load_key_and_certificates(p12, password.encode() if password else None)
	try:
		wwdr = x509.load_pem_x509_certificate(wwdr_raw)
	except ValueError:
		wwdr = x509.load_der_x509_certificate(wwdr_raw)
	return key, cert, wwdr


def sign_manifest(manifest: bytes, material=None) -> bytes:
	"""Detached PKCS#7 signature of manifest.json by the pass certificate, WWDR included."""
	from cryptography.hazmat.primitives import hashes
	from cryptography.hazmat.primitives.serialization import Encoding, pkcs7

	key, cert, wwdr = material or _signing_material()
	return (
		pkcs7.PKCS7SignatureBuilder()
		.set_data(manifest)
		.add_signer(cert, key, hashes.SHA256())
		.add_certificate(wwdr)
		.sign(Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary])
	)


def package(files: dict[str, bytes], signer=sign_manifest) -> bytes:
	"""Zip the files with manifest.json (SHA-1 of each) and its signature into a .pkpass."""
	manifest = json.dumps({name: hashlib.sha1(data).hexdigest() for name, data in files.items()}, sort_keys=True).encode()
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
		for name, data in files.items():
			archive.writestr(name, data)
		archive.writestr("manifest.json", manifest)
		archive.writestr("signature", signer(manifest))
	return buffer.getvalue()


def build_pkpass(view, pass_doc) -> bytes:
	files = {"pass.json": json.dumps(build_pass_json(view, pass_doc)).encode(), **_images()}
	return package(files)


# ---------------------------------------------------------------- push


# Tokens APNs will never accept: retrying them would fail the pass forever.
DEAD_TOKEN_REASONS = {"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"}


def _reason(response) -> str | None:
	try:
		return (response.json() or {}).get("reason")
	except ValueError:
		return None


def push_devices(pass_doc) -> int:
	"""Tell every device holding the pass to fetch it again. Returns the pushes APNs accepted."""
	registrations = frappe.get_all(DEVICE_REGISTRATION, filters={"pass": pass_doc.name}, fields=["name", "push_token"])
	if not registrations:
		return 0
	try:
		import httpx
	except ImportError as exc:
		raise WalletError("httpx[http2] is required for Apple Wallet pushes") from exc

	from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

	settings = get_settings()
	key, cert, _wwdr = _signing_material()
	host = APNS_HOSTS.get(settings.apple_apns_environment or "Production", APNS_HOSTS["Production"])

	paths = []
	try:
		for data in (cert.public_bytes(Encoding.PEM), key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())):
			handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
			handle.write(data)
			handle.close()
			paths.append(handle.name)

		accepted, failures = 0, []
		with httpx.Client(http2=True, cert=(paths[0], paths[1]), timeout=15) as client:
			for row in registrations:
				response = client.post(
					f"https://{host}/3/device/{row.push_token}",
					headers={"apns-topic": settings.apple_pass_type_id},
					content=b"{}",
				)
				if response.status_code == 200:
					accepted += 1
				elif response.status_code == 410 or _reason(response) in DEAD_TOKEN_REASONS:
					frappe.delete_doc(DEVICE_REGISTRATION, row.name, ignore_permissions=True, force=True)
				else:
					failures.append(f"{response.status_code} {response.text[:200]}")
		if failures:
			# Even when other devices took it: the pass is then marked failed
			# and retried, and a repeat push to a device that already has the
			# update only makes it ask again and hear "nothing changed".
			raise WalletError(
				f"APNs refused {len(failures)} of {len(registrations)} pushes: " + "; ".join(failures)
			)
		return accepted
	finally:
		for path in paths:
			os.unlink(path)


def update(pass_doc, view):
	push_devices(pass_doc)


def void(pass_doc, view):
	push_devices(pass_doc)
