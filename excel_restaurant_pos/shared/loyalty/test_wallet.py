# Copyright (c) 2026, Excel and contributors
# See license.txt

import base64
import datetime
import hashlib
import io
import json
import time
import zipfile
from unittest.mock import patch

import frappe
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.loyalty.wallet import apple, google
from excel_restaurant_pos.shared.loyalty.wallet.base import payload_hash

SETTINGS = frappe._dict(
	apple_pass_type_id="pass.com.example.loyalty",
	apple_team_id="TEAM123",
	apple_organization_name="Example",
	apple_web_service_url="https://pos.example.com/loyalty-wallet/apple/",
	google_issuer_id="3388000000012345678",
)

VIEW = frappe._dict(
	member_number="LM-ABCDEFGH",
	customer_name="Jane",
	programme="P",
	programme_name="Rewards",
	programme_end_date=None,
	balance=120,
	value=1.2,
	value_text="$1.20",
	currency="CAD",
	pending=10,
	tier="Gold",
	tier_benefits="Free dessert",
	next_expiry_date="2026-12-01",
	next_expiry_points=40,
	token="AL1.LM-ABCDEFGH.1.0123456789abcdef",
	state="active",
	background_color="#112233",
	foreground_color="#ffffff",
	label_color="#cccccc",
	terms="Terms apply",
)


def self_signed():
	key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Pass Type ID: pass.com.example.loyalty")])
	now = datetime.datetime.utcnow()
	cert = (
		x509.CertificateBuilder()
		.subject_name(name)
		.issuer_name(name)
		.public_key(key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(now)
		.not_valid_after(now + datetime.timedelta(days=1))
		.sign(key, hashes.SHA256())
	)
	return key, cert


class TestApplePass(FrappeTestCase):
	@patch("excel_restaurant_pos.shared.loyalty.wallet.apple.get_settings", return_value=SETTINGS)
	def test_pass_json(self, _settings):
		body = apple.build_pass_json(VIEW, frappe._dict(object_id="LM-ABCDEFGH"), auth_token="t" * 32)
		self.assertEqual(body["serialNumber"], "LM-ABCDEFGH")
		self.assertEqual(body["barcodes"][0]["message"], VIEW.token)
		self.assertEqual(body["storeCard"]["primaryFields"][0]["value"], 120)
		self.assertEqual(body["backgroundColor"], "rgb(17, 34, 51)")
		self.assertEqual(body["webServiceURL"], "https://pos.example.com/loyalty-wallet/apple")
		self.assertNotIn("voided", body)
		voided = apple.build_pass_json(frappe._dict(VIEW, state="voided"), frappe._dict(object_id="X"), auth_token="t" * 32)
		self.assertTrue(voided["voided"])

	def test_package_manifest_and_detached_signature(self):
		key, cert = self_signed()
		files = {"pass.json": b'{"a": 1}', "icon.png": b"\x89PNG fake"}
		data = apple.package(files, signer=lambda manifest: apple.sign_manifest(manifest, material=(key, cert, cert)))

		archive = zipfile.ZipFile(io.BytesIO(data))
		manifest = json.loads(archive.read("manifest.json"))
		self.assertEqual(manifest["pass.json"], hashlib.sha1(files["pass.json"]).hexdigest())
		self.assertEqual(set(archive.namelist()), {"pass.json", "icon.png", "manifest.json", "signature"})
		self.assertIn(cert, pkcs7.load_der_pkcs7_certificates(archive.read("signature")))

	def test_partial_push_failure_is_recorded_and_dead_tokens_dropped(self):
		import sys
		import types

		replies = {
			"ok": (200, b""),
			"dead": (400, b'{"reason": "BadDeviceToken"}'),
			"busy": (503, b'{"reason": "ServiceUnavailable"}'),
		}

		class Response:
			def __init__(self, status, body):
				self.status_code, self.text, self._body = status, body.decode(), body

			def json(self):
				return json.loads(self._body)

		class Client:
			def __init__(self, *args, **kwargs):
				pass

			def __enter__(self):
				return self

			def __exit__(self, *exc):
				return False

			def post(self, url, **kwargs):
				return Response(*replies[url.rsplit("/", 1)[-1]])

		key, cert = self_signed()
		registrations = [frappe._dict(name=f"REG-{t}", push_token=t) for t in replies]
		settings = frappe._dict(SETTINGS, apple_apns_environment="Sandbox")
		with patch.dict(sys.modules, {"httpx": types.SimpleNamespace(Client=Client)}), patch.object(
			apple, "get_settings", return_value=settings
		), patch.object(apple, "_signing_material", return_value=(key, cert, cert)), patch.object(
			apple.frappe, "get_all", return_value=registrations
		), patch.object(apple.frappe, "delete_doc") as delete_doc:
			# One device of three refused: the pass is not reported as synced.
			with self.assertRaisesRegex(apple.WalletError, "1 of 3"):
				apple.push_devices(frappe._dict(name="PASS-1"))
			delete_doc.assert_called_once_with(
				apple.DEVICE_REGISTRATION, "REG-dead", ignore_permissions=True, force=True
			)

			registrations.pop()
			self.assertEqual(apple.push_devices(frappe._dict(name="PASS-1")), 1)

	def test_token_hash_is_one_way(self):
		self.assertEqual(apple.hash_token("abc"), hashlib.sha256(b"abc").hexdigest())
		self.assertNotEqual(apple.hash_token("abc"), "abc")


class TestGoogleCallback(FrappeTestCase):
	def sign(self, key, data):
		return base64.b64encode(key.sign(data, ec.ECDSA(hashes.SHA256()))).decode()

	def public(self, key):
		return base64.b64encode(
			key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
		).decode()

	def payload(self, root, intermediate, message):
		signed_key = json.dumps({"keyValue": self.public(intermediate), "keyExpiration": str(int(time.time() * 1000) + 60000)})
		signed_message = json.dumps(message)
		key_data = google.length_value(b"GooglePayPasses", b"ECv2SigningOnly", signed_key.encode())
		message_data = google.length_value(
			b"GooglePayPasses", SETTINGS.google_issuer_id.encode(), b"ECv2SigningOnly", signed_message.encode()
		)
		return {
			"protocolVersion": "ECv2SigningOnly",
			"intermediateSigningKey": {"signedKey": signed_key, "signatures": [self.sign(root, key_data)]},
			"signedMessage": signed_message,
			"signature": self.sign(intermediate, message_data),
		}

	@patch("excel_restaurant_pos.shared.loyalty.wallet.google.get_settings", return_value=SETTINGS)
	def test_valid_and_tampered_callbacks(self, _settings):
		root, intermediate = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
		message = {"objectId": "x.LM-1", "eventType": "save", "expTimeMillis": int(time.time() * 1000) + 60000, "nonce": "n1"}
		payload = self.payload(root, intermediate, message)
		self.assertEqual(google.verify_callback(payload, root_keys=[self.public(root)])["eventType"], "save")

		tampered = dict(payload, signedMessage=payload["signedMessage"].replace("save", "del"))
		with self.assertRaises(google.WalletError):
			google.verify_callback(tampered, root_keys=[self.public(root)])

		stranger = ec.generate_private_key(ec.SECP256R1())
		with self.assertRaises(google.WalletError):
			google.verify_callback(payload, root_keys=[self.public(stranger)])

	@patch("excel_restaurant_pos.shared.loyalty.wallet.google.get_programme", return_value=frappe._dict(programme_name="Rewards"))
	@patch("excel_restaurant_pos.shared.loyalty.wallet.google.get_settings", return_value=SETTINGS)
	def test_object(self, _settings, _programme):
		body = google.build_object(VIEW)
		self.assertEqual(body["id"], "3388000000012345678.LM-ABCDEFGH")
		self.assertEqual(body["loyaltyPoints"]["balance"]["int"], 120)
		self.assertEqual(body["secondaryLoyaltyPoints"]["balance"]["money"]["micros"], 1_200_000)
		self.assertEqual(body["barcode"]["value"], VIEW.token)
		self.assertEqual(google.build_object(frappe._dict(VIEW, state="voided"))["state"], "INACTIVE")


class TestPayloadHash(FrappeTestCase):
	def test_stable_and_platform_specific(self):
		self.assertEqual(payload_hash(VIEW, "Google"), payload_hash(dict(VIEW), "Google"))
		self.assertNotEqual(payload_hash(VIEW, "Google"), payload_hash(VIEW, "Apple"))
		self.assertNotEqual(payload_hash(VIEW, "Google"), payload_hash(frappe._dict(VIEW, balance=121), "Google"))
