# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from excel_restaurant_pos.shared.antispam.honeypot import (
	HONEYPOT_FIELDS,
	MIN_CHECKOUT_SECONDS,
	check_order_honeypot,
)

MODULE = "excel_restaurant_pos.shared.antispam.honeypot"


def _order(**fields):
	return frappe._dict(customer="CUST-1", company="Bancan Kitchen POS", **fields)


def _ago(seconds):
	return str(add_to_date(now_datetime(), seconds=-seconds))


class TestHoneypotFields(FrappeTestCase):
	def setUp(self):
		patcher = patch(f"{MODULE}.frappe.log_error")
		self.log_error = patcher.start()
		self.addCleanup(patcher.stop)

	def test_a_normal_order_passes(self):
		check_order_honeypot(_order())

	def test_every_honeypot_field_is_checked(self):
		for fieldname in HONEYPOT_FIELDS:
			with self.subTest(field=fieldname):
				with self.assertRaises(frappe.ValidationError):
					check_order_honeypot(_order(**{fieldname: "http://spam.example"}))

	def test_an_empty_honeypot_is_not_a_bot(self):
		# A form that renders the field and submits it blank is the normal case.
		for value in ("", "   ", None):
			check_order_honeypot(_order(website=value))

	def test_the_rejection_says_nothing_useful(self):
		"""Naming the field that fired would be a tutorial on evading it."""
		with self.assertRaises(frappe.ValidationError) as raised:
			check_order_honeypot(_order(website="spam"))

		message = str(raised.exception).lower()
		for leak in ("honeypot", "website", "fax", "bot"):
			self.assertNotIn(leak, message)

	def test_a_trip_is_logged(self):
		with self.assertRaises(frappe.ValidationError):
			check_order_honeypot(_order(fax_number="1"))

		self.log_error.assert_called_once()
		self.assertIn("honeypot", self.log_error.call_args.kwargs["title"])


class TestCheckoutTiming(FrappeTestCase):
	def setUp(self):
		patcher = patch(f"{MODULE}.frappe.log_error")
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_an_instant_submission_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			check_order_honeypot(_order(checkout_started_at=_ago(0)))

	def test_a_human_paced_submission_passes(self):
		check_order_honeypot(_order(checkout_started_at=_ago(MIN_CHECKOUT_SECONDS + 30)))

	def test_omitting_the_timestamp_is_allowed(self):
		# Backward compatible: an existing client sends nothing and still works.
		check_order_honeypot(_order())

	def test_a_stale_tab_is_left_alone(self):
		# Someone who wandered off mid order should not be refused.
		check_order_honeypot(_order(checkout_started_at=_ago(60 * 60 * 24)))

	def test_a_clock_ahead_of_the_server_is_left_alone(self):
		check_order_honeypot(_order(checkout_started_at=str(add_to_date(now_datetime(), seconds=120))))

	def test_a_malformed_timestamp_does_not_refuse_a_real_order(self):
		check_order_honeypot(_order(checkout_started_at="not a date"))


class TestKillSwitch(FrappeTestCase):
	def test_site_config_can_disable_the_guard(self):
		"""A broken client must not be able to take ordering down."""
		with patch.dict(frappe.conf, {"arcpos_disable_order_honeypot": 1}):
			check_order_honeypot(_order(website="spam", checkout_started_at=_ago(0)))


def _utc_ago(seconds):
	"""What the storefront sends: new Date().toISOString()."""
	from datetime import datetime, timedelta, timezone

	moment = datetime.now(timezone.utc) - timedelta(seconds=seconds)
	return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _toronto_ago(seconds):
	from datetime import datetime, timedelta
	from zoneinfo import ZoneInfo

	return (datetime.now(ZoneInfo("America/Toronto")) - timedelta(seconds=seconds)).isoformat()


class TestCheckoutTimingAcrossTimezones(FrappeTestCase):
	"""Customers are in Canada; the site runs on another timezone entirely.

	Comparing the device's local time with the server's clock put every real
	order hours "old", past the stale-tab cutoff, so the check never ran.
	"""

	def setUp(self):
		patcher = patch(f"{MODULE}.frappe.log_error")
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_an_instant_utc_submission_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			check_order_honeypot(_order(checkout_started_at=_utc_ago(0)))

	def test_a_human_paced_utc_submission_passes(self):
		check_order_honeypot(_order(checkout_started_at=_utc_ago(MIN_CHECKOUT_SECONDS + 30)))

	def test_a_canadian_offset_timestamp_is_understood(self):
		with self.assertRaises(frappe.ValidationError):
			check_order_honeypot(_order(checkout_started_at=_toronto_ago(0)))
		check_order_honeypot(_order(checkout_started_at=_toronto_ago(MIN_CHECKOUT_SECONDS + 30)))

	def test_a_timezone_aware_value_never_breaks_an_order(self):
		# Subtracting aware from naive raises; that must never surface as a 500.
		check_order_honeypot(_order(checkout_started_at="2026-09-21T10:00:00+99:00"))
