# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.sales_invoice import order_limit

MODULE = "excel_restaurant_pos.shared.sales_invoice.order_limit"


@patch(f"{MODULE}.frappe.log_error")
class TestCustomerHourlyOrderLimit(FrappeTestCase):
	def check(self, limit, placed):
		with patch(f"{MODULE}.hourly_limit", return_value=limit), \
		     patch(f"{MODULE}.orders_in_window", return_value=placed):
			order_limit.check_customer_order_limit("CUST-LIMIT")

	def test_under_the_limit_is_allowed(self, _log):
		self.check(limit=5, placed=4)

	def test_at_the_limit_is_refused(self, _log):
		with self.assertRaises(frappe.ValidationError) as refused:
			self.check(limit=5, placed=5)
		self.assertIn("5 orders in the last hour", str(refused.exception))

	def test_zero_means_no_limit(self, _log):
		self.check(limit=0, placed=500)

	def test_the_number_comes_from_settings(self, _log):
		with patch(f"{MODULE}.frappe.db.get_single_value", return_value=3) as read:
			self.assertEqual(order_limit.hourly_limit(), 3)
		read.assert_called_once_with("ArcPOS Settings", "max_orders_per_customer_per_hour")

	def test_only_the_last_hour_of_this_customers_orders_count(self, _log):
		with patch(f"{MODULE}.frappe.db.count", return_value=2) as count:
			self.assertEqual(order_limit.orders_in_window("CUST-LIMIT"), 2)
		doctype, filters = count.call_args.args
		self.assertEqual(doctype, "Sales Invoice")
		self.assertEqual(filters["customer"], "CUST-LIMIT")
		self.assertEqual(filters["creation"][0], ">=")


class TestTheOrderEndpointAppliesIt(FrappeTestCase):
	"""add_or_update_invoice runs the check for customers and skips staff."""

	ENDPOINT = "excel_restaurant_pos.api.sales_invoice.add_or_update_invoice"

	def place(self, staff):
		import importlib

		module = importlib.import_module(self.ENDPOINT)
		frappe.local.form_dict = frappe._dict(customer="CUST-LIMIT", items=[])
		stop = frappe.ValidationError("stop after the guards")
		with patch(f"{self.ENDPOINT}.require_login", return_value="someone@example.com"), \
		     patch(f"{self.ENDPOINT}.is_staff", return_value=staff), \
		     patch(f"{self.ENDPOINT}.own_customer_or_refuse", return_value="CUST-LIMIT"), \
		     patch(f"{self.ENDPOINT}.check_order_honeypot"), \
		     patch(f"{self.ENDPOINT}.verify_order_turnstile", side_effect=stop), \
		     patch(f"{self.ENDPOINT}.check_customer_order_limit") as limit:
			with self.assertRaises(frappe.ValidationError):
				module.add_or_update_invoice()
		return limit

	def test_a_customer_is_checked(self):
		self.place(staff=False).assert_called_once_with("CUST-LIMIT")

	def test_staff_are_not(self):
		self.place(staff=True).assert_not_called()
