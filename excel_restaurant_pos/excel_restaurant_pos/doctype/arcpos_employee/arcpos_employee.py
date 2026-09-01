# Copyright (c) 2026, Sohanur Rahman and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from excel_restaurant_pos.shared.timeclock.pin import hash_pin, is_hashed_pin, normalize_pin


class ArcPOSEmployee(Document):
	def validate(self):
		self.employee_name = (self.employee_name or "").strip()
		self.set_pin()
		self.validate_unique_pin()

	def set_pin(self):
		"""Hash a newly entered PIN and drop the plain text before the doc is stored."""
		if self.new_pin:
			self.pin = hash_pin(normalize_pin(self.new_pin))
			self.new_pin = None
		elif self.pin and not is_hashed_pin(self.pin):
			# PIN set directly on the field (data import, API) — hash it too.
			self.pin = hash_pin(normalize_pin(self.pin))

		if not self.pin:
			frappe.throw(_("A 6-digit PIN is required"), frappe.MandatoryError)

	def validate_unique_pin(self):
		"""Two active employees may not share a PIN — the numpad identifies them by it."""
		if not self.is_active:
			return

		filters = {"pin": self.pin, "is_active": 1}
		if not self.is_new():
			filters["name"] = ("!=", self.name)

		duplicate = frappe.db.get_value("ArcPOS Employee", filters, ["name", "employee_name"], as_dict=True)
		if duplicate:
			frappe.throw(
				_("PIN is already used by {0} (Employee {1})").format(duplicate.employee_name, duplicate.name),
				frappe.DuplicateEntryError,
			)
