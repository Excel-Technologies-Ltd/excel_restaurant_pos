# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.antispam import turnstile

MODULE = "excel_restaurant_pos.shared.antispam.turnstile"
SECRET = {turnstile.SECRET_CONFIG_KEY: "0x-secret"}


def _order(**fields):
	return frappe._dict(customer="CUST-1", **fields)


def _with_token(token="tok-abc"):
	return _order(**{"cf-turnstile-response": token})


class _TurnstileCase(FrappeTestCase):
	def setUp(self):
		patcher = patch(f"{MODULE}.frappe.log_error")
		self.log_error = patcher.start()
		self.addCleanup(patcher.stop)

		# Guest unless a test says otherwise.
		previous = frappe.session.user
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, previous)


class TestWhenItRuns(_TurnstileCase):
	def test_no_secret_means_switched_off(self):
		"""The backend must be deployable before the storefront sends tokens."""
		with patch.dict(frappe.conf, {turnstile.SECRET_CONFIG_KEY: None}):
			self.assertFalse(turnstile.configured())
			turnstile.verify_order_turnstile(_order())

	def test_the_kill_switch_wins(self):
		with patch.dict(frappe.conf, {**SECRET, turnstile.DISABLE_CONFIG_KEY: 1}):
			self.assertFalse(turnstile.configured())
			turnstile.verify_order_turnstile(_order())

	@patch(f"{MODULE}._siteverify")
	def test_a_signed_in_caller_is_not_challenged(self, siteverify):
		"""Staff on a POS terminal hit the same endpoint."""
		frappe.set_user("Administrator")
		with patch.dict(frappe.conf, SECRET):
			turnstile.verify_order_turnstile(_order())

		siteverify.assert_not_called()


class TestTokenHandling(_TurnstileCase):
	@patch(f"{MODULE}._siteverify", return_value={"success": True})
	def test_every_accepted_field_name(self, _siteverify):
		for fieldname in turnstile.TOKEN_FIELDS:
			with self.subTest(field=fieldname), patch.dict(frappe.conf, SECRET):
				turnstile.verify_order_turnstile(_order(**{fieldname: "tok-abc"}))

	@patch(f"{MODULE}._siteverify")
	def test_a_missing_token_is_refused_without_calling_cloudflare(self, siteverify):
		with patch.dict(frappe.conf, SECRET):
			with self.assertRaises(frappe.ValidationError):
				turnstile.verify_order_turnstile(_order())

		siteverify.assert_not_called()

	@patch(f"{MODULE}._siteverify", return_value={"success": True})
	def test_a_valid_token_passes(self, _siteverify):
		with patch.dict(frappe.conf, SECRET):
			turnstile.verify_order_turnstile(_with_token())

	@patch(f"{MODULE}._siteverify", return_value={"success": False, "error-codes": ["timeout-or-duplicate"]})
	def test_a_replayed_token_is_refused(self, _siteverify):
		# This is the case the honeypot cannot catch: the request was copied out
		# of the network tab, so its token is already spent.
		with patch.dict(frappe.conf, SECRET):
			with self.assertRaises(frappe.ValidationError):
				turnstile.verify_order_turnstile(_with_token())

	@patch(f"{MODULE}._siteverify", return_value={"success": False, "error-codes": ["invalid-input-response"]})
	def test_the_refusal_says_nothing_useful(self, _siteverify):
		with patch.dict(frappe.conf, SECRET):
			with self.assertRaises(frappe.ValidationError) as raised:
				turnstile.verify_order_turnstile(_with_token())

		message = str(raised.exception).lower()
		for leak in ("turnstile", "captcha", "cloudflare", "token", "bot"):
			self.assertNotIn(leak, message)


class TestFailureModes(_TurnstileCase):
	"""Whose fault it is decides whether the order goes through."""

	@patch(f"{MODULE}._siteverify", return_value=None)
	def test_cloudflare_unreachable_lets_the_order_through(self, _siteverify):
		# A restaurant must not stop taking orders during someone else's outage.
		with patch.dict(frappe.conf, SECRET):
			turnstile.verify_order_turnstile(_with_token())

	@patch(f"{MODULE}._siteverify", return_value={"success": False, "error-codes": ["invalid-input-secret"]})
	def test_our_own_bad_keys_let_the_order_through(self, _siteverify):
		with patch.dict(frappe.conf, SECRET):
			turnstile.verify_order_turnstile(_with_token())

		self.assertIn("misconfigured", self.log_error.call_args.kwargs["title"])

	@patch(f"{MODULE}.requests")
	def test_a_timeout_is_no_opinion_rather_than_a_refusal(self, requests):
		requests.post.side_effect = TimeoutError("took too long")
		self.assertIsNone(turnstile._siteverify("0x-secret", "tok-abc"))

	@patch(f"{MODULE}.requests")
	def test_a_5xx_is_no_opinion(self, requests):
		requests.post.return_value = MagicMock(status_code=503)
		self.assertIsNone(turnstile._siteverify("0x-secret", "tok-abc"))

	@patch(f"{MODULE}.requests")
	def test_a_non_json_body_is_no_opinion(self, requests):
		response = MagicMock(status_code=200)
		response.json.side_effect = ValueError("not json")
		requests.post.return_value = response
		self.assertIsNone(turnstile._siteverify("0x-secret", "tok-abc"))

	@patch(f"{MODULE}.requests")
	def test_the_call_is_bounded(self, requests):
		requests.post.return_value = MagicMock(status_code=200, **{"json.return_value": {"success": True}})
		turnstile._siteverify("0x-secret", "tok-abc")
		self.assertEqual(requests.post.call_args.kwargs["timeout"], turnstile.VERIFY_TIMEOUT)

	@patch(f"{MODULE}.requests")
	def test_the_secret_is_never_logged(self, requests):
		requests.post.side_effect = TimeoutError("boom")
		turnstile._siteverify("0x-super-secret", "tok-abc")
		logged = str(self.log_error.call_args.kwargs.get("message", ""))
		self.assertNotIn("0x-super-secret", logged)


class TestActionBinding(_TurnstileCase):
	@patch(f"{MODULE}._siteverify", return_value={"success": True, "action": "checkout"})
	def test_the_expected_action_passes(self, _siteverify):
		with patch.dict(frappe.conf, {**SECRET, turnstile.ACTION_CONFIG_KEY: "checkout"}):
			turnstile.verify_order_turnstile(_with_token())

	@patch(f"{MODULE}._siteverify", return_value={"success": True, "action": "signup"})
	def test_a_token_from_another_widget_is_refused(self, _siteverify):
		with patch.dict(frappe.conf, {**SECRET, turnstile.ACTION_CONFIG_KEY: "checkout"}):
			with self.assertRaises(frappe.ValidationError):
				turnstile.verify_order_turnstile(_with_token())

	@patch(f"{MODULE}._siteverify", return_value={"success": True, "action": "anything"})
	def test_no_expected_action_means_no_check(self, _siteverify):
		with patch.dict(frappe.conf, SECRET):
			turnstile.verify_order_turnstile(_with_token())
