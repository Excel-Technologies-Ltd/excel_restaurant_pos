# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from excel_restaurant_pos.api.reservation import create_reservation as module

MODULE = "excel_restaurant_pos.api.reservation.create_reservation"


class TestReservationSpamGuards(FrappeTestCase):
	def setUp(self):
		# create_reservation commits; keep every test's rows inside its rollback.
		for target in (f"{MODULE}.frappe.db.commit", f"{MODULE}.frappe.log_error"):
			patcher = patch(target)
			patcher.start()
			self.addCleanup(patcher.stop)
		frappe.cache().delete_value(module.FLOOD_ALERT_CACHE_KEY)
		# FrappeTestCase rolls back per class; bookings must not pile up between tests.
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Guest")

	def book(self, **overrides):
		fields = {
			"guest_name": "Test Guest",
			"email": "guest.spam@example.com",
			"phone_number": "+15550100",
			"reservation_date": add_days(nowdate(), 3),
			"reservation_time": "19:00:00",
			"number_of_guests": 2,
			"requested_from": "Test",
		}
		fields.update(overrides)
		frappe.local.form_dict = frappe._dict(fields)
		return module.create_reservation()

	def test_a_normal_reservation_goes_through(self):
		self.assertTrue(self.book()["success"])

	def test_too_many_guests(self):
		result = self.book(number_of_guests=module.MAX_GUESTS + 1)
		self.assertFalse(result["success"])
		self.assertIn("call us", result["message"])

	def test_too_far_ahead(self):
		self.assertFalse(self.book(reservation_date=add_days(nowdate(), module.MAX_DAYS_AHEAD + 1))["success"])

	def test_oversized_text(self):
		self.assertFalse(self.book(special_requests="x" * 1001)["success"])

	def test_a_bad_time(self):
		self.assertFalse(self.book(reservation_time="not a time")["success"])

	def test_the_same_booking_twice(self):
		self.assertTrue(self.book()["success"])
		result = self.book()
		self.assertFalse(result["success"])
		self.assertIn("already have a reservation", result["message"])

	def test_one_contact_holds_only_a_few_pending(self):
		self.assertTrue(self.book(reservation_time="18:00:00")["success"])
		self.assertTrue(self.book(reservation_time="19:00:00")["success"])
		# A different email but the same phone is the same person.
		result = self.book(reservation_time="20:00:00", email="other.address@example.com")
		self.assertFalse(result["success"])
		self.assertIn("waiting for confirmation", result["message"])

	def test_a_flood_is_refused_and_staff_alerted_once(self):
		with patch(f"{MODULE}.frappe.db.count", return_value=module.SITE_HOURLY_LIMIT), \
		     patch(f"{MODULE}._alert_staff_of_flood", wraps=module._alert_staff_of_flood) as alert:
			first = self.book(email="a@example.com", phone_number="1")
			second = self.book(email="b@example.com", phone_number="2")

		self.assertFalse(first["success"])
		self.assertFalse(second["success"])
		self.assertEqual(alert.call_count, 2)
		self.assertTrue(frappe.cache().get_value(module.FLOOD_ALERT_CACHE_KEY, expires=True))
		# The log is written once; the second call found the flag and returned.
		self.assertEqual(module.frappe.log_error.call_count, 1)
