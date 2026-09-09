# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.sales_invoice.utils import fill_required_payment_entry_fields

MODULE = "excel_restaurant_pos.shared.sales_invoice.utils"


def _payment_entry(**fields):
	entry = MagicMock()
	entry.get.side_effect = lambda field, default=None: fields.get(field, default)
	return entry


def _invoice(territory=None, customer="CUST-1"):
	return frappe._dict(territory=territory, customer=customer)


class TestRequiredPaymentEntryFields(FrappeTestCase):
	"""excel_erpnext makes excel_territory mandatory with nothing to fill it.

	Left unset, every Payment Entry built in code dies on validation -- which
	took down the gateway payment flow, since api.payments.receipt_payment
	creates one inline after the customer has already been charged.
	"""

	@patch(f"{MODULE}.frappe.get_meta")
	def test_territory_is_taken_from_the_invoice(self, get_meta):
		get_meta.return_value.has_field.return_value = True
		entry = _payment_entry()

		fill_required_payment_entry_fields(entry, _invoice(territory="Eglinton Ave E"))

		self.assertEqual(entry.excel_territory, "Eglinton Ave E")

	@patch(f"{MODULE}.frappe.db.get_value", return_value="Downtown")
	@patch(f"{MODULE}.frappe.get_meta")
	def test_it_falls_back_to_the_customer(self, get_meta, get_value):
		# A Sales Invoice can carry no territory of its own.
		get_meta.return_value.has_field.return_value = True
		entry = _payment_entry()

		fill_required_payment_entry_fields(entry, _invoice(territory=None))

		self.assertEqual(entry.excel_territory, "Downtown")
		get_value.assert_called_once_with("Customer", "CUST-1", "territory")

	@patch(f"{MODULE}.frappe.get_meta")
	def test_an_existing_value_is_left_alone(self, get_meta):
		get_meta.return_value.has_field.return_value = True
		entry = _payment_entry(excel_territory="Already Set")

		fill_required_payment_entry_fields(entry, _invoice(territory="Eglinton Ave E"))

		# The mock would record an assignment; nothing should have been written.
		self.assertNotIn("excel_territory", [call[0] for call in entry.method_calls])
		self.assertEqual(entry.get("excel_territory"), "Already Set")

	@patch(f"{MODULE}.frappe.get_meta")
	def test_a_site_without_the_field_is_untouched(self, get_meta):
		# The field belongs to another app, which may not be installed.
		get_meta.return_value.has_field.return_value = False
		entry = _payment_entry()

		fill_required_payment_entry_fields(entry, _invoice(territory="Eglinton Ave E"))

		self.assertEqual(entry.get("excel_territory"), None)

	@patch(f"{MODULE}.frappe.db.get_value", return_value=None)
	@patch(f"{MODULE}.frappe.get_meta")
	def test_nothing_is_written_when_no_territory_can_be_found(self, get_meta, _get_value):
		# Better to let Frappe raise its own mandatory error than to invent one.
		get_meta.return_value.has_field.return_value = True
		entry = _payment_entry()

		fill_required_payment_entry_fields(entry, _invoice(territory=None))

		self.assertEqual(entry.get("excel_territory"), None)
