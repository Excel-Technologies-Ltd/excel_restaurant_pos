# Copyright (c) 2026, Sohanur Rahman and Contributors
# See license.txt

import itertools

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.timeclock.services import (
	check_in,
	check_out,
	create_manual_entry,
	update_record,
)

BUSINESS_DATE = "2026-09-01"


# FrappeTestCase rolls back once per class (addClassCleanup), not per test, so
# everything an earlier test in the class inserted is still there for the next
# one. A fixed PIN in setUp therefore collides with itself from the second test
# onwards -- PINs have to be unique per test, not per class.
_pin_counter = itertools.count(900001)


def next_pin() -> str:
	return str(next(_pin_counter))


def create_employee(employee_name: str, pin: str, role: str = "Waiter", timeclock_cost: float = 20.0):
	doc = frappe.new_doc("ArcPOS Employee")
	doc.employee_name = employee_name
	doc.role = role
	doc.timeclock_cost = timeclock_cost
	doc.new_pin = pin
	doc.insert()
	return doc


class TestEmployeeTimeclockTracking(FrappeTestCase):
	def setUp(self):
		# A fresh employee per test: the record name is ETT-<date>-<employee>,
		# so a shared employee would collide on BUSINESS_DATE too.
		self.employee = create_employee("Timeclock Test Waiter", next_pin())

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
		other = create_employee("Timeclock Test Barista", next_pin(), role="Barista")
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


class TestEmployeeTimeclockCost(FrappeTestCase):
	def _record_for(self, employee, business_date=BUSINESS_DATE):
		record = frappe.new_doc("Employee Timeclock Tracking")
		record.employee = employee.name
		record.business_date = business_date
		record.first_check_in = f"{business_date} 09:00:00"
		record.last_check_out = f"{business_date} 17:00:00"
		record.insert()
		return record

	def test_rate_comes_from_the_employee(self):
		employee = create_employee("Cost Test Chef", next_pin(), role="Chef", timeclock_cost=31.25)

		record = self._record_for(employee)

		self.assertEqual(record.timeclock_cost, 31.25)
		self.assertEqual(record.total_paid_hours, 8.0)
		self.assertEqual(record.total_payment, 250.0)

	def test_each_employee_is_costed_at_their_own_rate(self):
		cheap = create_employee("Cost Test Janitor", next_pin(), role="Janitor", timeclock_cost=12.0)
		dear = create_employee("Cost Test Bartender", next_pin(), role="Bartender", timeclock_cost=40.0)

		self.assertEqual(self._record_for(cheap).total_payment, 96.0)
		self.assertEqual(self._record_for(dear).total_payment, 320.0)

	def test_employee_without_a_rate_costs_nothing(self):
		# The column is `not null default 0`, so an employee that predates the
		# field reads back as 0 rather than blank. The v1_8_0 patch seeds those;
		# an employee left at 0 after it is a deliberate 0.
		employee = create_employee("Cost Test Unpaid", next_pin(), timeclock_cost=0)

		record = self._record_for(employee)

		self.assertEqual(record.timeclock_cost, 0.0)
		self.assertEqual(record.total_payment, 0.0)

	def test_later_rate_change_does_not_reprice_a_past_shift(self):
		employee = create_employee("Cost Test Raise", next_pin(), timeclock_cost=10.0)
		record = self._record_for(employee)

		employee.timeclock_cost = 50.0
		employee.save()

		record.reload()
		record.save()

		self.assertEqual(record.timeclock_cost, 10.0)
		self.assertEqual(record.total_payment, 80.0)


class TestTimeclockRemarks(FrappeTestCase):
	"""`remarks` follows the same omitted/empty rule as the timestamps."""

	def setUp(self):
		self.employee = create_employee("Remarks Test Chef", next_pin(), role="Chef")
		self.identity = frappe._dict(
			name=self.employee.name,
			employee_name=self.employee.employee_name,
			role=self.employee.role,
		)

	def test_check_in_stores_a_trimmed_note(self):
		result = check_in(self.identity, remarks="  arrived late, traffic  ")

		self.assertEqual(result["record"]["remarks"], "arrived late, traffic")

	def test_omitting_remarks_leaves_the_note_alone(self):
		# Otherwise a check out with no note silently wipes the one left at
		# check in, which is how the shift context gets lost.
		check_in(self.identity, remarks="arrived late")

		result = check_out(self.identity)

		self.assertEqual(result["record"]["remarks"], "arrived late")

	def test_empty_remarks_clears_the_note(self):
		check_in(self.identity, remarks="arrived late")

		result = check_out(self.identity, remarks="")

		self.assertIsNone(result["record"]["remarks"])

	def test_manager_edit_sets_the_note(self):
		record = check_in(self.identity)["record"]
		manager = create_employee("Remarks Test Manager", next_pin(), role="Manager")

		result = update_record(
			manager, self.employee.name, record["business_date"], remarks="fixed a missed check out"
		)

		self.assertEqual(result["record"]["remarks"], "fixed a missed check out")

	def test_manual_entry_carries_the_note(self):
		manager = create_employee("Remarks Entry Manager", next_pin(), role="Manager")

		result = create_manual_entry(
			manager,
			self.employee.name,
			"2026-08-01",
			"2026-08-01 09:00:00",
			last_check_out="2026-08-01 17:00:00",
			remarks="forgot to clock in",
		)

		self.assertEqual(result["record"]["remarks"], "forgot to clock in")

