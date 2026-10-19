# Copyright (c) 2026, Excel and contributors
# See license.txt

"""Pure unit tests: FIFO lot planning, member tokens, campaign windows, redemption limits."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.loyalty import accounts, ledger, redemption
from excel_restaurant_pos.shared.loyalty.campaigns import parse_days, window_open
from excel_restaurant_pos.shared.loyalty.expiry import notice_offsets
from excel_restaurant_pos.shared.loyalty.reversal import return_ratio


class TestAllocation(FrappeTestCase):
	LOTS = [
		{"name": "L1", "remaining_points": 30, "expiry_date": "2026-11-01"},
		{"name": "L2", "remaining_points": 50, "expiry_date": "2026-12-01"},
		{"name": "L3", "remaining_points": 20, "expiry_date": None},
	]

	def test_fifo_consumes_earliest_expiry_first(self):
		allocations, shortfall = ledger.plan_allocation(self.LOTS, 60)
		self.assertEqual([(a["lot"], a["points"]) for a in allocations], [("L1", 30), ("L2", 30)])
		self.assertEqual(shortfall, 0)

	def test_shortfall(self):
		_allocations, shortfall = ledger.plan_allocation(self.LOTS, 120)
		self.assertEqual(shortfall, 20)

	def test_restore_latest_expiry_first_and_partial_restores_do_not_overlap(self):
		allocations = [
			{"lot": "L1", "points": 30, "lot_expiry_date": "2026-11-01"},
			{"lot": "L2", "points": 30, "lot_expiry_date": "2026-12-01"},
		]
		self.assertEqual(ledger.plan_restore(allocations, 0, 40), [(30, "2026-12-01"), (10, "2026-11-01")])
		self.assertEqual(ledger.plan_restore(allocations, 40, 40), [(20, "2026-11-01")])


class TestMemberToken(FrappeTestCase):
	SECRET = "s3cret"

	def test_round_trip(self):
		token = accounts.build_token("LM-ABCDEFGH", 2, self.SECRET)
		self.assertTrue(token.startswith("AL1.LM-ABCDEFGH.2."))
		self.assertEqual(accounts.parse_token(token, self.SECRET), ("LM-ABCDEFGH", 2))

	def test_tampering_rejected(self):
		token = accounts.build_token("LM-ABCDEFGH", 2, self.SECRET)
		self.assertIsNone(accounts.parse_token(token.replace(".2.", ".3."), self.SECRET))
		self.assertIsNone(accounts.parse_token(token, "other-secret"))
		self.assertIsNone(accounts.parse_token("AL1.LM-ABCDEFGH.2.zz", self.SECRET))

	def test_masking(self):
		self.assertEqual(accounts.mask_email("jane.doe@example.com"), "j***@e***.com")
		self.assertEqual(accounts.mask_phone("+1 (416) 555-0199"), "***0199")


class TestCampaignWindows(FrappeTestCase):
	def test_weekly_days(self):
		campaign = {
			"start_datetime": "2026-10-01 00:00:00",
			"end_datetime": "2026-12-31 23:59:59",
			"recurrence": "Weekly",
			"recurrence_days": "Fri, sat",
		}
		self.assertEqual(parse_days("Fri, sat, xyz"), {"Fri", "Sat"})
		self.assertTrue(window_open(campaign, "2026-10-16 12:00:00"))  # Friday
		self.assertFalse(window_open(campaign, "2026-10-15 12:00:00"))  # Thursday
		self.assertFalse(window_open(campaign, "2027-01-01 12:00:00"))  # Friday, past the end

	def test_daily_time_window_including_overnight(self):
		happy = {
			"start_datetime": "2026-01-01 00:00:00",
			"recurrence": "Weekly",
			"recurrence_start_time": "22:00:00",
			"recurrence_end_time": "02:00:00",
		}
		self.assertTrue(window_open(happy, "2026-10-16 23:30:00"))
		self.assertTrue(window_open(happy, "2026-10-17 01:30:00"))
		self.assertFalse(window_open(happy, "2026-10-17 12:00:00"))

	def test_overnight_window_belongs_to_the_day_it_opened(self):
		friday_night = {
			"start_datetime": "2026-01-01 00:00:00",
			"recurrence": "Weekly",
			"recurrence_days": "Fri",
			"recurrence_start_time": "22:00:00",
			"recurrence_end_time": "02:00:00",
		}
		self.assertTrue(window_open(friday_night, "2026-10-16 23:30:00"))  # Friday night
		self.assertTrue(window_open(friday_night, "2026-10-17 01:30:00"))  # small hours of Saturday
		self.assertFalse(window_open(friday_night, "2026-10-16 01:30:00"))  # Thursday night's tail
		self.assertFalse(window_open(friday_night, "2026-10-17 23:30:00"))  # Saturday night

	def test_feb_29_birthdays_on_the_28th_in_other_years(self):
		from frappe.utils import getdate

		from excel_restaurant_pos.shared.loyalty.events import birthday_days

		self.assertEqual(birthday_days(getdate("2027-02-28")), [28, 29])
		self.assertEqual(birthday_days(getdate("2028-02-28")), [28])
		self.assertEqual(birthday_days(getdate("2028-02-29")), [29])
		self.assertEqual(birthday_days(getdate("2027-03-01")), [1])

	def test_yearly_window_repeats(self):
		festival = {"start_datetime": "2025-12-20 00:00:00", "end_datetime": "2026-01-05 23:59:59", "recurrence": "Yearly"}
		self.assertTrue(window_open(festival, "2026-12-25 10:00:00"))
		self.assertTrue(window_open(festival, "2027-01-02 10:00:00"))
		self.assertFalse(window_open(festival, "2026-06-01 10:00:00"))

	def test_one_off_window(self):
		once = {"start_datetime": "2026-10-10 00:00:00", "end_datetime": "2026-10-12 00:00:00", "recurrence": "None"}
		self.assertFalse(window_open(once, "2026-10-09 23:59:59"))
		self.assertTrue(window_open(once, "2026-10-11 00:00:00"))
		self.assertFalse(window_open(once, "2026-10-12 00:00:01"))

	def test_notice_offsets(self):
		self.assertEqual(notice_offsets(frappe._dict(expiry_notice_days="7, 30,1,x,0")), [30, 7, 1])


class TestRedemptionOptions(FrappeTestCase):
	def programme(self, **fields):
		values = {
			"point_value": 0.01,
			"redeem_increment": 100,
			"max_redeem_percent_of_order": 50,
			"min_redeem_points": 200,
			"max_redeem_points_per_order": 0,
		}
		values.update(fields)
		return frappe._dict(values)

	def doc(self, total):
		return frappe._dict(docstatus=0, grand_total=total, customer="C1", posting_date="2026-10-18")

	@patch("excel_restaurant_pos.shared.loyalty.ledger.available_balance", return_value=5000)
	def test_percent_cap_and_increment(self, _balance):
		opts = redemption.options(self.doc(30), "LM-X", self.programme())
		# 50% of 30.00 = 15.00 -> 1500 points, already a multiple of 100.
		self.assertEqual(opts["max_points"], 1500)
		self.assertEqual(opts["min_points"], 200)
		self.assertTrue(opts["redeemable"])

	@patch("excel_restaurant_pos.shared.loyalty.ledger.available_balance", return_value=950)
	def test_rounds_down_to_increment_and_balance(self, _balance):
		self.assertEqual(redemption.options(self.doc(100), "LM-X", self.programme())["max_points"], 900)

	@patch("excel_restaurant_pos.shared.loyalty.ledger.available_balance", return_value=150)
	def test_below_minimum_not_redeemable(self, _balance):
		self.assertFalse(redemption.options(self.doc(100), "LM-X", self.programme())["redeemable"])

	@patch("excel_restaurant_pos.shared.loyalty.ledger.available_balance", return_value=5000)
	def test_max_per_order(self, _balance):
		opts = redemption.options(self.doc(100), "LM-X", self.programme(max_redeem_points_per_order=700))
		self.assertEqual(opts["max_points"], 700)

	def test_check_points_messages(self):
		opts = {"step": 100, "min_points": 200, "max_points": 900, "available_points": 950}
		for bad in (150, 250, 1000, 0):
			with self.assertRaises(frappe.ValidationError):
				redemption._check_points(bad, opts)
		redemption._check_points(300, opts)

	def test_amount_due(self):
		applied = frappe._dict(grand_total=20, custom_loyalty_points_redeemed=500, custom_loyalty_redeem_value=5)
		self.assertEqual(redemption.amount_due(applied), 15)
		self.assertEqual(redemption.amount_due(frappe._dict(grand_total=20)), 20)


class TestReturnRatio(FrappeTestCase):
	def test_item_rule_reverses_only_returned_items(self):
		original = {"BURGER": {"amount": 60, "qty": 2}, "COLA": {"amount": 40, "qty": 4}}
		returned = {"COLA": {"amount": 40, "qty": 4}}
		item_row = frappe._dict(basis_items='["BURGER"]', basis_qty=2)
		self.assertEqual(return_ratio(item_row, original, returned, 100, -40), 0)
		spend_row = frappe._dict(basis_items=None, basis_qty=0)
		self.assertAlmostEqual(return_ratio(spend_row, original, returned, 100, -40), 0.4)
