# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.utils.rate_limit import rate_limit_by_caller


class TestRateLimitByCaller(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_keys("arcpos:rate:test_endpoint:*")

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
