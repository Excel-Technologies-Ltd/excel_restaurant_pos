# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.auth import login as login_module
from excel_restaurant_pos.overrides import user as signup_module
from excel_restaurant_pos.shared.antispam import turnstile
from excel_restaurant_pos.shared.web_customer import web_customer_roles

LOGIN = "excel_restaurant_pos.api.auth.login"
TURNSTILE = "excel_restaurant_pos.shared.antispam.turnstile"
SIGNUP = "excel_restaurant_pos.overrides.user"
ON = {turnstile.SECRET_CONFIG_KEY: "0x-secret"}
CUSTOMER, STAFF, PWD = "guard.customer@example.com", "guard.staff@example.com", "Guard!Pass#2026"
TOKEN = {"cf-turnstile-response": "tok-abc"}


def _user(email, *roles):
	user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Guard", "new_password": PWD})
	user.flags.no_welcome_mail = True
	user.flags.ignore_password_policy = True
	user.insert(ignore_permissions=True)
	user.add_roles(*roles)


class _GuardCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(CUSTOMER, *web_customer_roles())
		_user(STAFF, "Restaurant Cashier")

	def setUp(self):
		for target in (f"{TURNSTILE}.frappe.log_error", f"{LOGIN}.frappe.log_error",
		               "excel_restaurant_pos.shared.antispam.honeypot.frappe.log_error"):
			patcher = patch(target)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")


@patch(f"{LOGIN}.should_run_2fa", return_value=False)
@patch(f"{LOGIN}.issue_login_response", return_value="signed in")
class TestLogin(_GuardCase):
	def login(self, email, pwd=PWD, **guards):
		return login_module.login(email, pwd, **guards)

	def test_without_turnstile_nothing_changes(self, *_mocks):
		with patch.dict(frappe.conf, {turnstile.SECRET_CONFIG_KEY: None}):
			self.assertEqual(self.login(CUSTOMER), "signed in")

	def test_staff_clients_need_no_widget(self, *_mocks):
		with patch.dict(frappe.conf, ON), patch(f"{TURNSTILE}._siteverify") as siteverify:
			self.assertEqual(self.login(STAFF), "signed in")
		siteverify.assert_not_called()

	@patch(f"{TURNSTILE}._siteverify", return_value={"success": True})
	def test_a_customer_with_a_good_token_signs_in(self, *_mocks):
		with patch.dict(frappe.conf, ON):
			self.assertEqual(self.login(CUSTOMER, **TOKEN), "signed in")

	def test_a_customer_without_a_token_looks_exactly_like_a_wrong_password(self, *_mocks):
		with patch.dict(frappe.conf, ON):
			with self.assertRaises(frappe.AuthenticationError) as right_password:
				self.login(CUSTOMER)
			with self.assertRaises(frappe.AuthenticationError) as wrong_password:
				self.login(CUSTOMER, pwd="not it")
		self.assertEqual(str(right_password.exception), str(wrong_password.exception))

	@patch(f"{TURNSTILE}._siteverify", return_value={"success": False, "error-codes": ["timeout-or-duplicate"]})
	def test_a_rejected_token_is_refused_before_the_password_is_checked(self, *_mocks):
		with patch.dict(frappe.conf, ON), patch("frappe.core.doctype.user.user.User.find_by_credentials") as check:
			with self.assertRaises(frappe.ValidationError) as refused:
				self.login(CUSTOMER, pwd="not it", **TOKEN)
		check.assert_not_called()
		self.assertIn("could not sign you in", str(refused.exception))

	def test_a_filled_honeypot_is_refused_before_the_password(self, *_mocks):
		with patch("frappe.core.doctype.user.user.User.find_by_credentials") as check:
			with self.assertRaises(frappe.ValidationError):
				self.login(CUSTOMER, website="http://spam.example")
		check.assert_not_called()

	def test_login_is_not_timed(self, *_mocks):
		# A password manager fills and submits it inside a second.
		from frappe.utils import now_datetime
		self.assertEqual(self.login(CUSTOMER, form_started_at=str(now_datetime())), "signed in")


@patch(f"{SIGNUP}.send_otp_email")
class TestSignUp(_GuardCase):
	def sign_up(self, email="guard.new@example.com", **guards):
		frappe.set_user("Guest")  # how every sign-up arrives
		return signup_module.sign_up(email, "+15550100", "New Guard", PWD, **guards)

	def test_without_turnstile_nothing_changes(self, send):
		with patch.dict(frappe.conf, {turnstile.SECRET_CONFIG_KEY: None}):
			self.assertTrue(self.sign_up()["success"])
		send.assert_called_once()

	@patch(f"{TURNSTILE}._siteverify", return_value={"success": True})
	def test_a_good_token_signs_up(self, _siteverify, send):
		with patch.dict(frappe.conf, ON):
			self.assertTrue(self.sign_up(**TOKEN)["success"])

	def test_no_token_is_refused_before_any_mail_or_lookup(self, send):
		with patch.dict(frappe.conf, ON):
			with self.assertRaises(frappe.ValidationError) as refused:
				# An existing address: the refusal must not reveal that either.
				self.sign_up(email=CUSTOMER)
		send.assert_not_called()
		self.assertIn("could not create your account", str(refused.exception))

	def test_a_filled_honeypot_is_refused(self, send):
		with self.assertRaises(frappe.ValidationError):
			self.sign_up(fax_number="1")
		send.assert_not_called()

	def test_a_form_filled_too_fast_is_refused(self, send):
		from frappe.utils import now_datetime
		with self.assertRaises(frappe.ValidationError):
			self.sign_up(form_started_at=str(now_datetime()))
		send.assert_not_called()


class TestWhichActionEachFormExpects(FrappeTestCase):
	def expected(self, configured, form):
		with patch.dict(frappe.conf, {turnstile.ACTION_CONFIG_KEY: configured}):
			return turnstile._expected_action(form)

	def test_unpinned(self):
		self.assertIsNone(self.expected(None, "login"))

	def test_the_old_string_setting_pins_checkout_and_the_rest_by_name(self):
		self.assertEqual(self.expected("checkout", "checkout"), "checkout")
		self.assertEqual(self.expected("checkout", "signup"), "signup")
		self.assertEqual(self.expected("checkout", "login"), "login")

	def test_a_plain_switch_pins_every_form_by_name(self):
		self.assertEqual(self.expected(1, "checkout"), "checkout")

	def test_a_dict_names_each(self):
		self.assertEqual(self.expected({"login": "sign-in"}, "login"), "sign-in")

	@patch(f"{TURNSTILE}.frappe.log_error")
	@patch(f"{TURNSTILE}._siteverify", return_value={"success": True, "action": "checkout"})
	def test_a_checkout_token_cannot_sign_in(self, *_mocks):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		with patch.dict(frappe.conf, {**ON, turnstile.ACTION_CONFIG_KEY: "checkout"}):
			with self.assertRaises(frappe.ValidationError):
				turnstile.verify_turnstile(TOKEN, "login")
