# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.auth import google
from excel_restaurant_pos.shared.web_customer import ensure_customer_for_user, web_customer_roles

MODULE = "excel_restaurant_pos.api.auth.google"
CLIENT_ID = "1234-test.apps.googleusercontent.com"
TEST_ZONE = "_Test Web Zone"
# excel_erpnext makes Customer.custom_zone mandatory, so web customers need one.
CONFIG = {
	google.CLIENT_IDS_CONFIG_KEY: [CLIENT_ID],
	"arcpos_web_customer_defaults": {"custom_zone": TEST_ZONE},
}
# throw_error raises AuthenticationError / PermissionError; frappe.throw raises
# ValidationError. Any of them is a refusal.
REFUSED = (frappe.AuthenticationError, frappe.PermissionError, frappe.ValidationError)


def _claims(email="google.newcomer@example.com", **overrides):
	claims = {
		"iss": "https://accounts.google.com",
		"aud": CLIENT_ID,
		"email": email,
		"email_verified": True,
		"given_name": "Google",
		"family_name": "Newcomer",
	}
	claims.update(overrides)
	return claims


class _GoogleCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if frappe.db.exists("DocType", "Zone") and not frappe.db.exists("Zone", TEST_ZONE):
			frappe.get_doc({"doctype": "Zone", "excel_zone_name": TEST_ZONE}).insert(ignore_permissions=True)

	def setUp(self):
		frappe.local.cookie_manager = MagicMock()
		patcher = patch(f"{MODULE}.frappe.log_error")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")

	def sign_in(self, claims, config=CONFIG):
		try:
			with patch.dict(frappe.conf, config), patch(
				f"{MODULE}.google_id_token.verify_oauth2_token", return_value=claims
			) as verify:
				result = google.google_login(credential="a.google.jwt")
		finally:
			# google_login drops to Guest, as password login does.
			frappe.set_user("Administrator")
		return result, verify


class TestTokenChecks(_GoogleCase):
	def test_off_until_a_client_id_is_configured(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_claims(), config={**CONFIG, google.CLIENT_IDS_CONFIG_KEY: None})

	def test_a_missing_credential_is_refused(self):
		with patch.dict(frappe.conf, CONFIG):
			with self.assertRaises(REFUSED):
				google.google_login(credential=None)

	def test_the_audience_is_our_client_id(self):
		"""Without this, a token Google issued to any other site would work here."""
		_result, verify = self.sign_in(_claims())
		self.assertEqual(verify.call_args.kwargs["audience"], [CLIENT_ID])

	def test_a_token_google_rejects_is_refused(self):
		# Bad signature, wrong audience, expired: google-auth raises for all.
		with patch.dict(frappe.conf, CONFIG), patch(
			f"{MODULE}.google_id_token.verify_oauth2_token", side_effect=ValueError("Wrong audience")
		):
			with self.assertRaises(REFUSED):
				google.google_login(credential="a.google.jwt")

	def test_a_foreign_issuer_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_claims(iss="https://evil.example"))

	def test_an_unverified_email_is_refused(self):
		with self.assertRaises(REFUSED):
			self.sign_in(_claims(email_verified=False))


class TestRealGoogleVerification(_GoogleCase):
	def test_a_forged_token_fails_real_verification(self):
		"""Through the actual google-auth library and Google's published keys."""
		forged = (
			"eyJhbGciOiJSUzI1NiIsImtpZCI6ImZha2UiLCJ0eXAiOiJKV1QifQ."
			"eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJlbWFpbCI6ImFAYi5jb20ifQ."
			"c2lnbmF0dXJl"
		)
		with patch.dict(frappe.conf, CONFIG):
			with self.assertRaises(REFUSED):
				google.google_login(credential=forged)


class TestAccounts(_GoogleCase):
	def test_a_first_time_google_user_gets_a_storefront_account(self):
		email = "google.first.time@example.com"

		result, _verify = self.sign_in(_claims(email=email))

		data = result["data"]
		self.assertTrue(data["access_token"])
		self.assertTrue(data["refresh_token"])
		self.assertEqual(data["user"]["email"], email)

		user = frappe.get_doc("User", {"email": email})
		# Created as a Website User, but Frappe makes it a System User the moment
		# Sales User (a Desk role) is added -- exactly as email sign-up does. The
		# two paths must match; that Sales User gives web customers Desk access is
		# the reason it needs replacing, in shared/web_customer.py, for both.
		self.assertTrue(set(web_customer_roles()).issubset(set(frappe.get_roles(user.name))))

		customer = frappe.db.get_value("Customer", {"email_id": email}, "name")
		self.assertTrue(customer)
		self.assertEqual(data["user"]["customer_id"], customer)
		self.assertTrue(frappe.db.exists("User Permission", {"user": user.name, "allow": "Customer", "for_value": customer}))

	def test_signing_in_again_reuses_the_account(self):
		email = "google.returning@example.com"
		self.sign_in(_claims(email=email))
		self.sign_in(_claims(email=email))

		self.assertEqual(frappe.db.count("User", {"email": email}), 1)
		self.assertEqual(frappe.db.count("Customer", {"email_id": email}), 1)

	def test_the_response_matches_password_login(self):
		result, _verify = self.sign_in(_claims(email="google.shape@example.com"))
		for key in ("access_token", "refresh_token", "token_type", "expires_in", "permissions", "user"):
			self.assertIn(key, result["data"])

	def test_a_staff_account_is_refused(self):
		"""A Google account must not sidestep a staff password and 2FA."""
		email = "google.staff@example.com"
		self.sign_in(_claims(email=email))
		frappe.get_doc("User", {"email": email}).add_roles("Restaurant Manager")

		with self.assertRaises(REFUSED):
			self.sign_in(_claims(email=email))

	def test_staff_can_be_allowed_deliberately(self):
		email = "google.staff.allowed@example.com"
		self.sign_in(_claims(email=email))
		frappe.get_doc("User", {"email": email}).add_roles("Restaurant Manager")

		result, _verify = self.sign_in(
			_claims(email=email), config={**CONFIG, google.ALLOW_STAFF_CONFIG_KEY: 1}
		)
		self.assertTrue(result["data"]["access_token"])

	def test_administrator_is_always_refused(self):
		admin_email = frappe.db.get_value("User", "Administrator", "email") or "admin@example.com"
		frappe.db.set_value("User", "Administrator", "email", admin_email)
		with self.assertRaises(REFUSED):
			self.sign_in(_claims(email=admin_email), config={**CONFIG, google.ALLOW_STAFF_CONFIG_KEY: 0})

	def test_a_disabled_account_is_refused(self):
		email = "google.disabled@example.com"
		self.sign_in(_claims(email=email))
		frappe.db.set_value("User", {"email": email}, "enabled", 0)

		with self.assertRaises(REFUSED):
			self.sign_in(_claims(email=email))


class TestSharedCustomerSetup(_GoogleCase):
	def test_an_existing_customer_still_gets_its_user_permissions(self):
		"""Sign-up used to skip them when the Customer already existed."""
		email = "pos.made.customer@example.com"
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "POS Made", "email_id": email,
			 "customer_type": "Individual", "customer_group": "All Customer Groups",
			 "territory": "All Territories", "custom_zone": TEST_ZONE}
		).insert(ignore_permissions=True).name
		user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "POS", "user_type": "Website User"})
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)

		self.assertEqual(ensure_customer_for_user(user), customer)
		self.assertTrue(frappe.db.exists("User Permission", {"user": user.name, "allow": "Customer", "for_value": customer}))
		self.assertEqual(frappe.db.count("Customer", {"email_id": email}), 1)


class TestTokenIssuingIsNotExposed(FrappeTestCase):
	def test_issue_login_response_cannot_be_called_over_http(self):
		"""It hands out tokens for whatever user it is given."""
		from excel_restaurant_pos.api.auth import login

		self.assertNotIn(login.issue_login_response, frappe.whitelisted)

	def test_google_login_is_post_only(self):
		self.assertIn(google.google_login, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[google.google_login], ["POST"])


class TestMissingRequiredCustomerField(_GoogleCase):
	def test_the_error_names_the_field_and_the_fix(self):
		if not frappe.get_meta("Customer").get_field("custom_zone"):
			self.skipTest("this site has no custom_zone")
		config = {google.CLIENT_IDS_CONFIG_KEY: [CLIENT_ID], "arcpos_web_customer_defaults": {}}

		with self.assertRaises(frappe.ValidationError) as raised:
			self.sign_in(_claims(email="google.nozone@example.com"), config=config)

		self.assertIn("custom_zone", str(raised.exception))
		self.assertIn("arcpos_web_customer_defaults", str(raised.exception))


class TestEmailSignUpIsAtomic(FrappeTestCase):
	def test_a_failed_sign_up_leaves_no_account(self):
		"""It used to commit a User with Sales User and no User Permission."""
		import json

		from excel_restaurant_pos.overrides import user as user_module

		key = "t" + frappe.generate_hash(length=10)
		email = "half.made@example.com"
		frappe.cache().set_value(
			f"signup_verification:{key}",
			json.dumps({"email": email, "full_name": "Half Made", "password": "Str0ng!Pass#99",
			            "otp": "ABC123", "mobile_no": None}),
		)
		with patch.object(user_module, "ensure_customer_for_user", side_effect=frappe.ValidationError("boom")), \
			patch.object(user_module.frappe, "log_error"):
			result = user_module.verify_otp(key, "ABC123")

		self.assertFalse(result["success"])
		self.assertFalse(frappe.db.exists("User", email))
