# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

CODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class ArcPOSLoyaltyEventType(Document):
	def before_naming(self):
		# The name is taken from event_code before validate runs; normalise it
		# first, or "Referral_Bonus" would name the record while rules match
		# the emitted code "referral_bonus" and never fire.
		self.event_code = (self.event_code or "").strip().lower()

	def validate(self):
		self.event_code = (self.event_code or "").strip().lower()
		if not CODE.match(self.event_code):
			frappe.throw(_("Event Code must be snake_case letters, digits and underscores, e.g. feedback_submitted."))

	def on_trash(self):
		if self.is_builtin:
			frappe.throw(_("Built-in event types cannot be deleted; disable them instead."))
