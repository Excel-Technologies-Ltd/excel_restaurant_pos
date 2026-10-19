# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


class ArcPOSLoyaltyReward(Document):
	def validate(self):
		if cint(self.points_cost) <= 0:
			frappe.throw(_("Points Cost must be greater than zero."))
		if self.reward_type == "Order Discount Voucher" and flt(self.discount_value) <= 0:
			frappe.throw(_("Discount Value is required for a discount voucher."))
		if self.discount_type == "Percentage" and flt(self.discount_value) > 100:
			frappe.throw(_("A percentage discount cannot exceed 100."))
		if self.active_from and self.active_to and getdate(self.active_to) < getdate(self.active_from):
			frappe.throw(_("Active To cannot be before Active From."))
