# Copyright (c) 2026, Excel and Contributors
# See license.txt

import importlib

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from excel_restaurant_pos.shared.item_price import is_live, live_prices

YESTERDAY, TODAY, TOMORROW = add_days(today(), -1), today(), add_days(today(), 1)


class TestIsLive(FrappeTestCase):
	def test_an_open_window_is_always_live(self):
		self.assertTrue(is_live(frappe._dict()))

	def test_a_price_that_has_not_started_is_not_live(self):
		"""The bug: an offer scheduled for next week was on sale this week."""
		self.assertFalse(is_live(frappe._dict(valid_from=TOMORROW)))

	def test_a_price_starting_today_is_live(self):
		self.assertTrue(is_live(frappe._dict(valid_from=TODAY)))

	def test_a_price_that_has_ended_is_not_live(self):
		self.assertFalse(is_live(frappe._dict(valid_upto=YESTERDAY)))

	def test_a_price_ending_today_is_still_live(self):
		self.assertTrue(is_live(frappe._dict(valid_upto=TODAY)))

	def test_a_future_window_becomes_live_on_its_start_date(self):
		price = frappe._dict(valid_from=TOMORROW)
		self.assertFalse(is_live(price, on_date=TODAY))
		self.assertTrue(is_live(price, on_date=TOMORROW))

	def test_live_prices_filters_a_list(self):
		rows = [frappe._dict(n=1), frappe._dict(n=2, valid_from=TOMORROW), frappe._dict(n=3, valid_upto=YESTERDAY)]
		self.assertEqual([r.n for r in live_prices(rows)], [1])


class TestReadersHonourTheStartDate(FrappeTestCase):
	"""Every reader, against real Item Price rows."""

	ITEM = "_Test Price Window Item"
	ADDON = "_Test Price Window Addon"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for code in (cls.ITEM, cls.ADDON):
			if not frappe.db.exists("Item", code):
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": code,
						"item_name": code,
						"item_group": "All Item Groups",
						"stock_uom": "Nos",
						"is_stock_item": 0,
						"has_excel_serials": "No",
						"description": code,
					}
				).insert(ignore_permissions=True)

		cls.standard = cls._price(cls.ITEM, "Standard Selling", 11, TODAY)
		# Scheduled to start tomorrow -- must not be on sale today.
		cls.offer = cls._price(cls.ITEM, "Offer Price", 10, TOMORROW)
		cls.addon = cls._price(cls.ADDON, "Add-on Price", 2, TOMORROW)

	@staticmethod
	def _price(item_code, price_list, rate, valid_from):
		return frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": item_code,
				"price_list": price_list,
				"price_list_rate": rate,
				"valid_from": valid_from,
			}
		).insert(ignore_permissions=True).name

	def _start(self, name, valid_from):
		frappe.db.set_value("Item Price", name, "valid_from", valid_from)

	def _lists(self, rows):
		return sorted(row["price_list"] for row in rows)

	def test_the_item_list_hides_an_offer_that_has_not_started(self):
		from excel_restaurant_pos.api.item.get_item_list import _attach_item_prices

		self._start(self.offer, TOMORROW)
		[item] = _attach_item_prices([frappe._dict(item_code=self.ITEM)])
		self.assertEqual(self._lists(item["prices"]), ["Standard Selling"])

	def test_the_item_list_shows_it_once_it_starts(self):
		from excel_restaurant_pos.api.item.get_item_list import _attach_item_prices

		self._start(self.offer, TODAY)
		[item] = _attach_item_prices([frappe._dict(item_code=self.ITEM)])
		self.assertEqual(self._lists(item["prices"]), ["Offer Price", "Standard Selling"])

	def test_the_item_popup_agrees_with_the_list(self):
		details = importlib.import_module("excel_restaurant_pos.api.item.get_item_details")

		self._start(self.offer, TOMORROW)
		self.assertEqual(self._lists(details._get_regular_price_map([self.ITEM])[self.ITEM]), ["Standard Selling"])

		self._start(self.offer, TODAY)
		self.assertEqual(
			self._lists(details._get_regular_price_map([self.ITEM])[self.ITEM]),
			["Offer Price", "Standard Selling"],
		)

	def test_add_on_prices_honour_their_dates(self):
		# These used to check neither end of the window.
		details = importlib.import_module("excel_restaurant_pos.api.item.get_item_details")

		self._start(self.addon, TOMORROW)
		self.assertNotIn(self.ADDON, details._get_addon_price_map([self.ADDON]))

		self._start(self.addon, TODAY)
		self.assertEqual(details._get_addon_price_map([self.ADDON])[self.ADDON], 2)
