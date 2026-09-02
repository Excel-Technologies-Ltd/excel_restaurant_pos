# Copyright (c) 2026, Sohanur Rahman and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt, get_datetime, getdate

from excel_restaurant_pos.shared.timeclock.services import compute_paid_hours, get_timeclock_cost


class EmployeeTimeclockTracking(Document):
	def before_insert(self):
		if not flt(self.timeclock_cost):
			self.timeclock_cost = get_timeclock_cost()

	def validate(self):
		self.validate_identity_unchanged()
		self.validate_timestamps()
		self.calculate_totals()

	def validate_identity_unchanged(self):
		"""Employee and business date form the record name, so they cannot move.

		Checked here rather than with `set_only_once`: that flag compares Link values
		raw, and `_validate_links` rewrites `employee` to the autoincrement name (an
		int) while the value loaded from the database is a string, so every save of an
		existing record would fail.
		"""
		before = self.get_doc_before_save()
		if not before:
			return

		if cstr(self.employee) != cstr(before.employee) or getdate(self.business_date) != getdate(
			before.business_date
		):
			frappe.throw(
				_("Employee and Business Date cannot be changed on an existing timeclock entry"),
				frappe.CannotChangeConstantError,
			)

	def validate_timestamps(self):
		if not (self.first_check_in and self.last_check_out):
			return

		if get_datetime(self.last_check_out) < get_datetime(self.first_check_in):
			frappe.throw(_("Last Check Out cannot be earlier than First Check In"))

	def calculate_totals(self):
		self.total_paid_hours = compute_paid_hours(self.first_check_in, self.last_check_out)
		self.total_payment = flt(flt(self.total_paid_hours) * flt(self.timeclock_cost))
