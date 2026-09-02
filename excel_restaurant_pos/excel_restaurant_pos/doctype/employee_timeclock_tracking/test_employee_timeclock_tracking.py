# Copyright (c) 2026, Sohanur Rahman and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.timeclock.services import check_in, check_out

BUSINESS_DATE = "2026-09-01"


def create_employee(employee_name: str, pin: str, role: str = "Waiter"):
	doc = frappe.new_doc("ArcPOS Employee")
	doc.employee_name = employee_name
	doc.role = role
	doc.new_pin = pin
	doc.insert()
	return doc


class TestEmployeeTimeclockTracking(FrappeTestCase):
	def setUp(self):
		self.employee = create_employee("Timeclock Test Waiter", "907531")

	def _make_record(self, first_check_in=f"{BUSINESS_DATE} 09:00:00"):
		record = frappe.new_doc("Employee Timeclock Tracking")
		record.employee = self.employee.name
		record.business_date = BUSINESS_DATE
		record.first_check_in = first_check_in
		record.insert()
		return record

	def test_existing_record_can_be_saved_again(self):
		# Check out and every manager edit re-save an existing record. `_validate_links`
		# rewrites `employee` to the autoincrement (int) name, so an identity check that
		# compares the raw value against the string loaded from the database would fail here.
		record = self._make_record()

		record.last_check_out = f"{BUSINESS_DATE} 17:30:00"
		record.save()

		self.assertEqual(record.total_paid_hours, 8.5)

	def test_employee_cannot_be_changed(self):
		other = create_employee("Timeclock Test Barista", "907532", role="Barista")
		record = self._make_record()

		record.employee = other.name
		self.assertRaises(frappe.CannotChangeConstantError, record.save)

	def test_business_date_cannot_be_changed(self):
		record = self._make_record()

		record.business_date = "2026-09-02"
		self.assertRaises(frappe.CannotChangeConstantError, record.save)

	def test_check_out_replaces_last_check_out(self):
		employee = frappe._dict(
			name=self.employee.name, employee_name=self.employee.employee_name, role=self.employee.role
		)

		check_in(employee)
		first = check_out(employee)["record"]["last_check_out"]
		second = check_out(employee)["record"]["last_check_out"]

		self.assertIsNotNone(first)
		self.assertIsNotNone(second)
		self.assertGreaterEqual(second, first)

	def test_check_out_before_check_in_is_rejected(self):
		record = self._make_record(first_check_in=f"{BUSINESS_DATE} 17:00:00")

		record.last_check_out = f"{BUSINESS_DATE} 09:00:00"
		self.assertRaises(frappe.ValidationError, record.save)
