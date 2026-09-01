# Copyright (c) 2026, Excel and Contributors
# See license.txt

import datetime

from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.timeclock.pin import hash_pin, is_hashed_pin, normalize_pin
from excel_restaurant_pos.shared.timeclock.services import (
	compute_paid_hours,
	get_business_date,
	get_business_day_window,
)


class TestTimeclockBusinessDay(FrappeTestCase):
	def test_business_date_before_cutoff_belongs_to_previous_day(self):
		# 04:00 AM and earlier still belongs to the previous business day
		self.assertEqual(get_business_date("2026-09-02 00:15:00"), datetime.date(2026, 9, 1))
		self.assertEqual(get_business_date("2026-09-02 03:59:59"), datetime.date(2026, 9, 1))
		self.assertEqual(get_business_date("2026-09-02 04:00:00"), datetime.date(2026, 9, 1))

	def test_business_date_after_cutoff_is_same_day(self):
		self.assertEqual(get_business_date("2026-09-02 04:01:00"), datetime.date(2026, 9, 2))
		self.assertEqual(get_business_date("2026-09-02 13:30:00"), datetime.date(2026, 9, 2))
		self.assertEqual(get_business_date("2026-09-02 23:59:59"), datetime.date(2026, 9, 2))

	def test_business_day_window(self):
		start, end = get_business_day_window("2026-09-02")
		self.assertEqual(start, datetime.datetime(2026, 9, 2, 4, 0, 1))
		self.assertEqual(end, datetime.datetime(2026, 9, 3, 4, 0, 0))


class TestTimeclockPaidHours(FrappeTestCase):
	def test_hours_between_check_in_and_check_out(self):
		self.assertEqual(compute_paid_hours("2026-09-01 10:00:00", "2026-09-01 18:30:00"), 8.5)

	def test_shift_crossing_midnight(self):
		self.assertEqual(compute_paid_hours("2026-09-01 20:00:00", "2026-09-02 02:00:00"), 6.0)

	def test_incomplete_or_inverted_shift_is_zero(self):
		self.assertEqual(compute_paid_hours("2026-09-01 10:00:00", None), 0.0)
		self.assertEqual(compute_paid_hours(None, "2026-09-01 10:00:00"), 0.0)
		self.assertEqual(compute_paid_hours("2026-09-01 18:00:00", "2026-09-01 10:00:00"), 0.0)


class TestTimeclockPin(FrappeTestCase):
	def test_pin_must_be_six_digits(self):
		self.assertEqual(normalize_pin(" 123456 "), "123456")
		for invalid in ("12345", "1234567", "12345a", "", None):
			with self.assertRaises(Exception):
				normalize_pin(invalid)

	def test_hash_is_deterministic_and_opaque(self):
		digest = hash_pin("123456")
		self.assertEqual(digest, hash_pin("123456"))
		self.assertNotEqual(digest, hash_pin("123457"))
		self.assertNotIn("123456", digest)
		self.assertTrue(is_hashed_pin(digest))
		self.assertFalse(is_hashed_pin("123456"))
