# Copyright (c) 2026, Excel and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.utils.rate_limit import (
	GUEST_API_DEFAULT_LIMIT,
	limit_guest_api_requests,
	rate_limit_by_caller,
)


class TestRateLimitByCaller(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_keys("arcpos:rate:test_endpoint:*")
		frappe.cache().delete_keys("arcpos:rate:guest_api:*")

	def test_requests_under_the_limit_pass(self):
		for _attempt in range(3):
			rate_limit_by_caller("test_endpoint", limit=3, seconds=60)

	def test_request_over_the_limit_is_rejected(self):
		for _attempt in range(3):
			rate_limit_by_caller("test_endpoint", limit=3, seconds=60)

		with self.assertRaises(frappe.ValidationError):
			rate_limit_by_caller("test_endpoint", limit=3, seconds=60)

	def test_guests_are_counted_per_ip(self):
		"""One guest exhausting their budget must not lock out another."""
		with patch.object(frappe.local, "request_ip", "10.0.0.1", create=True):
			with patch.object(frappe.session, "user", "Guest"):
				for _attempt in range(2):
					rate_limit_by_caller("test_endpoint", limit=2, seconds=60)

				with self.assertRaises(frappe.ValidationError):
					rate_limit_by_caller("test_endpoint", limit=2, seconds=60)

		with patch.object(frappe.local, "request_ip", "10.0.0.2", create=True):
			with patch.object(frappe.session, "user", "Guest"):
				# A different address still has its full budget.
				rate_limit_by_caller("test_endpoint", limit=2, seconds=60)

	def test_logged_in_callers_are_counted_per_user(self):
		with patch.object(frappe.local, "request_ip", "10.0.0.1", create=True):
			rate_limit_by_caller("test_endpoint", limit=1, seconds=60)

			with self.assertRaises(frappe.ValidationError):
				rate_limit_by_caller("test_endpoint", limit=1, seconds=60)

			# Same address, different user: separate counter.
			with patch.object(frappe.session, "user", "Guest"):
				rate_limit_by_caller("test_endpoint", limit=1, seconds=60)


class TestLimitGuestApiRequests(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_keys("arcpos:rate:guest_api:*")

	def _as_guest_api(self, path, method="POST", ip="10.1.2.3"):
		request = SimpleNamespace(path=path, method=method)
		return (
			patch.object(frappe.local, "request", request, create=True),
			patch.object(frappe.local, "request_ip", ip, create=True),
			patch.object(frappe.session, "user", "Guest"),
		)

	def test_skips_non_api_method_paths(self):
		request = SimpleNamespace(path="/app/home", method="GET")
		with patch.object(frappe.local, "request", request, create=True):
			with patch.object(frappe.session, "user", "Guest"):
				limit_guest_api_requests()  # must not throw

	def test_skips_authenticated_users(self):
		request = SimpleNamespace(path="/api/method/api.sales_invoices.add", method="POST")
		with patch.object(frappe.local, "request", request, create=True):
			with patch.object(frappe.session, "user", "Administrator"):
				for _attempt in range(GUEST_API_DEFAULT_LIMIT + 5):
					limit_guest_api_requests()

	def test_skips_exempt_webhooks(self):
		patches = self._as_guest_api("/api/method/api.uber_eats.webhook")
		with patches[0], patches[1], patches[2]:
			for _attempt in range(GUEST_API_DEFAULT_LIMIT + 5):
				limit_guest_api_requests()

	def test_blocks_guest_write_burst_on_order_create(self):
		patches = self._as_guest_api("/api/method/api.sales_invoices.add")
		with patches[0], patches[1], patches[2]:
			# Strict write limit for this method is 10/min.
			for _attempt in range(10):
				limit_guest_api_requests()
			with self.assertRaises(frappe.ValidationError):
				limit_guest_api_requests()

	def test_strict_write_limit_applies_even_on_get(self):
		"""Mutations must not bypass strict caps via GET."""
		patches = self._as_guest_api(
			"/api/method/api.sales_invoices.add", method="GET"
		)
		with patches[0], patches[1], patches[2]:
			for _attempt in range(10):
				limit_guest_api_requests()
			with self.assertRaises(frappe.ValidationError):
				limit_guest_api_requests()

	def test_jwt_bearer_skips_guest_budget(self):
		"""Valid JWT applied early must not consume the guest IP budget."""
		request = SimpleNamespace(
			path="/api/method/api.sales_invoices.add", method="POST"
		)

		def _set_user():
			frappe.session.user = "pos@example.com"

		with patch.object(frappe.local, "request", request, create=True):
			with patch.object(frappe.local, "request_ip", "10.1.2.3", create=True):
				with patch.object(frappe.session, "user", "Guest"):
					with patch(
						"frappe.get_request_header",
						return_value="Bearer fake.token",
					):
						with patch(
							"excel_restaurant_pos.auth.validate",
							side_effect=_set_user,
						):
							for _attempt in range(15):
								limit_guest_api_requests()

	def test_different_ips_have_separate_budgets(self):
		for ip in ("10.1.2.3", "10.1.2.4"):
			patches = self._as_guest_api(
				"/api/method/api.sales_invoices.add", ip=ip
			)
			with patches[0], patches[1], patches[2]:
				limit_guest_api_requests()
