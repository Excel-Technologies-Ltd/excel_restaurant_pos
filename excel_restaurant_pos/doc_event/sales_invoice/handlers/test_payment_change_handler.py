# Copyright (c) 2026, Excel and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.doc_event.sales_invoice.handlers.payment_change_handler import payment_change_handler

MODULE = "excel_restaurant_pos.doc_event.sales_invoice.handlers.payment_change_handler"


class _Invoice(SimpleNamespace):
	# Not frappe._dict: its `items` would be dict.items, not the item rows.
	def get(self, fieldname, default=None):
		return getattr(self, fieldname, default)


def _invoice(**fields):
	return _Invoice(name="TEST", status="Paid", items=[SimpleNamespace()], save=MagicMock(), **fields)


class TestEmptyFields(FrappeTestCase):
	def test_a_dine_in_order_without_a_schedule_type_closes(self):
		# The field exists but is empty (None) -- it used to crash on .lower().
		invoice = _invoice(custom_service_type="Dine-in", custom_order_type="Pay Later",
		                   custom_order_from=None, custom_order_schedule_type=None)
		with patch(f"{MODULE}.frappe.get_doc", return_value=invoice):
			payment_change_handler("ORD-TEST")

		self.assertEqual(invoice.custom_order_status, "Closed")
		invoice.save.assert_called_once()

	def test_a_paid_pickup_without_a_schedule_type_goes_to_the_kitchen(self):
		invoice = _invoice(custom_service_type="Pickup", custom_order_type="Pay First",
		                   custom_order_from="Website", custom_order_schedule_type=None)
		with patch(f"{MODULE}.frappe.get_doc", return_value=invoice):
			payment_change_handler("WEB-TEST")

		self.assertEqual(invoice.custom_order_status, "In kitchen")
