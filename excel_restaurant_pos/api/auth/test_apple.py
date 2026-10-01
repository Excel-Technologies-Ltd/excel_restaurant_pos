# Copyright (c) 2026, Excel and Contributors
# See license.txt

import json
import time
from unittest.mock import MagicMock, patch

import frappe
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.auth import apple
from excel_restaurant_pos.shared.web_customer import web_customer_roles

MODULE = "excel_restaurant_pos.api.auth.apple"
WEB_CLIENT_ID = "com.example.arcpos.web"
IOS_CLIENT_ID = "com.example.arcpos"
TEST_ZONE = "_Test Web Zone"
KID = "test-apple-key"
# excel_erpnext makes Customer.custom_zone mandatory, so web customers need one.
CONFIG = {
	apple.CLIENT_IDS_CONFIG_KEY: [WEB_CLIENT_ID, IOS_CLIENT_ID],
	"arcpos_web_customer_defaults": {"custom_zone": TEST_ZONE},
}
# throw_error raises AuthenticationError / PermissionError; frappe.throw raises
# ValidationError. Any of them is a refusal.
REFUSED = (frappe.AuthenticationError, frappe.PermissionError, frappe.ValidationError)

APPLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
REAL_FETCH = apple._fetch_apple_keys


def _jwk(private_key, kid=KID):
	jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
	jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
	return jwk


def _claims(email="apple.newcomer@example.com", **overrides):
	now = int(time.time())
	claims = {
		"iss": apple.APPLE_ISSUER,
		"aud": WEB_CLIENT_ID,
		"sub": "001234.abcdef.1234",
		"iat": now,
		"exp": now + 600,
		"email": email,
		"email_verified": "true",
	}
	claims.update(overrides)
	return {k: v for k, v in claims.items() if v is not None}


def _token(claims, key=APPLE_KEY, kid=KID, algorithm="RS256"):
	return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


class _AppleCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if frappe.db.exists("DocType", "Zone") and not frappe.db.exists("Zone", TEST_ZONE):
			frappe.get_doc({"doctype": "Zone", "excel_zone_name": TEST_ZONE}).insert(ignore_permissions=True)

	def setUp(self):
		frappe.local.cookie_manager = MagicMock()
		for key in (apple.KEYS_CACHE_KEY, apple.KEYS_REFRESH_LOCK_KEY):
			frappe.cache().delete_value(key)
			self.addCleanup(frappe.cache().delete_value, key)
		patcher = patch(f"{MODULE}.frappe.log_error")
		patcher.start()
		self.addCleanup(patcher.stop)
		fetch = patch(f"{MODULE}._fetch_apple_keys", return_value=[_jwk(APPLE_KEY)])
		self.fetch = fetch.start()
		self.addCleanup(fetch.stop)
		self.addCleanup(frappe.set_user, "Administrator")

	def sign_in(self, token, config=CONFIG, **names):
		try:
			with patch.dict(frappe.conf, config):
				return apple.apple_login(credential=token, **names)
		finally:
			# apple_login drops to Guest, as password login does.
			frappe.set_user("Administrator")


class TestTokenChecks(_AppleCase):
	def test_off_until_a_client_id_is_configured(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims()), config={**CONFIG, apple.CLIENT_IDS_CONFIG_KEY: None})

	def test_a_missing_credential_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in(None)

	def test_a_malformed_credential_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in("not.a.jwt")

	def test_web_and_ios_client_ids_are_both_accepted(self):
		for index, client_id in enumerate((WEB_CLIENT_ID, IOS_CLIENT_ID)):
			result = self.sign_in(_token(_claims(email=f"apple.client{index}@example.com", aud=client_id)))
			self.assertTrue(result["data"]["access_token"])

	def test_a_token_for_another_app_is_refused(self):
		"""Without this, a token Apple issued to any other app would work here."""
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(aud="com.someone.else")))

	def test_a_foreign_issuer_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(iss="https://evil.example")))

	def test_an_expired_token_is_refused(self):
		now = int(time.time())
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(iat=now - 3600, exp=now - 600)))

	def test_a_token_without_expiry_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(exp=None)))

	def test_a_token_signed_by_another_key_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(), key=OTHER_KEY))

	def test_an_hs256_token_is_refused(self):
		"""The algorithm is pinned, not taken from the token."""
		token = jwt.encode(_claims(), "secret", algorithm="HS256", headers={"kid": KID})
		with self.assertRaises(REFUSED):
			self.sign_in(token)

	def test_an_unsigned_token_is_refused(self):
		token = jwt.encode(_claims(), None, algorithm="none", headers={"kid": KID})
		with self.assertRaises(REFUSED):
			self.sign_in(token)

	def test_an_unverified_email_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(email_verified="false")))

	def test_a_token_without_email_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(email=None)))

	def test_email_verified_may_be_a_boolean(self):
		result = self.sign_in(_token(_claims(email="apple.bool@example.com", email_verified=True)))
		self.assertTrue(result["data"]["access_token"])

	def test_apple_being_unreachable_is_a_refusal(self):
		self.fetch.side_effect = ConnectionError("appleid.apple.com unreachable")
		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims()))


class TestKeyCache(_AppleCase):
	def test_keys_are_fetched_once_and_cached(self):
		self.sign_in(_token(_claims(email="apple.cache1@example.com")))
		self.sign_in(_token(_claims(email="apple.cache2@example.com")))
		self.assertEqual(self.fetch.call_count, 1)

	def test_a_rotated_key_is_picked_up(self):
		self.sign_in(_token(_claims(email="apple.rotate1@example.com")))
		self.fetch.return_value = [_jwk(APPLE_KEY), _jwk(OTHER_KEY, kid="rotated")]

		result = self.sign_in(_token(_claims(email="apple.rotate2@example.com"), key=OTHER_KEY, kid="rotated"))
		self.assertTrue(result["data"]["access_token"])
		self.assertEqual(self.fetch.call_count, 2)

	def test_made_up_key_ids_do_not_refetch_every_time(self):
		self.sign_in(_token(_claims(email="apple.kid@example.com")))
		for kid in ("made-up-1", "made-up-2", "made-up-3"):
			with self.assertRaises(REFUSED):
				self.sign_in(_token(_claims(), key=OTHER_KEY, kid=kid))
		# The first load, then one refresh for the first unknown kid only.
		self.assertEqual(self.fetch.call_count, 2)


class TestRealAppleVerification(_AppleCase):
	def test_a_forged_token_fails_real_verification(self):
		"""Against Apple's live published keys."""
		self.fetch.side_effect = REAL_FETCH
		forged = _token(_claims(), key=OTHER_KEY, kid="fake")
		with self.assertRaises(REFUSED):
			self.sign_in(forged)


class TestAccounts(_AppleCase):
	def test_a_first_time_apple_user_gets_a_storefront_account(self):
		email = "apple.first.time@example.com"

		result = self.sign_in(_token(_claims(email=email)), first_name=" Apple ", last_name="Person")

		data = result["data"]
		self.assertTrue(data["access_token"])
		self.assertTrue(data["refresh_token"])
		self.assertEqual(data["user"]["email"], email)

		user = frappe.get_doc("User", {"email": email})
		self.assertEqual((user.first_name, user.last_name), ("Apple", "Person"))
		self.assertTrue(set(web_customer_roles()).issubset(set(frappe.get_roles(user.name))))
		self.assertNotIn("Sales User", frappe.get_roles(user.name))
		self.assertEqual(user.user_type, "Website User")

		customer = frappe.db.get_value("Customer", {"email_id": email}, "name")
		self.assertTrue(customer)
		self.assertEqual(data["user"]["customer_id"], customer)

	def test_a_hidden_email_relay_address_works(self):
		email = "abc123xyz@privaterelay.appleid.com"
		result = self.sign_in(_token(_claims(email=email, is_private_email="true")))
		self.assertEqual(result["data"]["user"]["email"], email)

	def test_without_a_name_the_email_stands_in(self):
		email = "apple.noname@example.com"
		self.sign_in(_token(_claims(email=email)))
		self.assertEqual(frappe.db.get_value("User", {"email": email}, "first_name"), email)

	def test_signing_in_again_reuses_the_account(self):
		email = "apple.returning@example.com"
		self.sign_in(_token(_claims(email=email)), first_name="First")
		self.sign_in(_token(_claims(email=email)), first_name="Changed")

		self.assertEqual(frappe.db.count("User", {"email": email}), 1)
		self.assertEqual(frappe.db.count("Customer", {"email_id": email}), 1)
		self.assertEqual(frappe.db.get_value("User", {"email": email}, "first_name"), "First")

	def test_the_response_matches_password_login(self):
		result = self.sign_in(_token(_claims(email="apple.shape@example.com")))
		for key in ("access_token", "refresh_token", "token_type", "expires_in", "permissions", "user"):
			self.assertIn(key, result["data"])

	def test_a_staff_account_is_refused(self):
		"""An Apple ID must not sidestep a staff password and 2FA."""
		email = "apple.staff@example.com"
		self.sign_in(_token(_claims(email=email)))
		frappe.get_doc("User", {"email": email}).add_roles("Restaurant Manager")

		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(email=email)))

	def test_staff_can_be_allowed_deliberately(self):
		email = "apple.staff.allowed@example.com"
		self.sign_in(_token(_claims(email=email)))
		frappe.get_doc("User", {"email": email}).add_roles("Restaurant Manager")

		result = self.sign_in(_token(_claims(email=email)), config={**CONFIG, apple.ALLOW_STAFF_CONFIG_KEY: 1})
		self.assertTrue(result["data"]["access_token"])

	def test_a_disabled_account_is_refused(self):
		email = "apple.disabled@example.com"
		self.sign_in(_token(_claims(email=email)))
		frappe.db.set_value("User", {"email": email}, "enabled", 0)

		with self.assertRaises(REFUSED):
			self.sign_in(_token(_claims(email=email)))


class TestEndpoint(FrappeTestCase):
	def test_apple_login_is_post_only(self):
		self.assertIn(apple.apple_login, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[apple.apple_login], ["POST"])
