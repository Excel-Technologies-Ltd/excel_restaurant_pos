# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from excel_restaurant_pos.shared.loyalty.rules import ensure_rule_ids


class ArcPOSLoyaltyProgramme(Document):
	def validate(self):
		ensure_rule_ids(self, "base_rules", "base_rule_items")
		self.validate_values()
		self.validate_tiers()
		self.validate_single_active()

	def validate_values(self):
		if flt(self.point_value) <= 0:
			frappe.throw(_("Value of 1 Point must be greater than zero."))
		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."))
		if cint(self.redeem_increment) < 1:
			self.redeem_increment = 1
		if not 0 < flt(self.max_redeem_percent_of_order) <= 100:
			frappe.throw(_("Max % of Order must be between 0 and 100."))
		if self.expiry_mode != "Never" and cint(self.expiry_days) <= 0:
			frappe.throw(_("Expiry Days is required for expiry mode {0}.").format(self.expiry_mode))
		for part in (self.expiry_notice_days or "").split(","):
			if part.strip() and not part.strip().isdigit():
				frappe.throw(_("Expiry Notice Days must be comma-separated numbers, e.g. 30,7,1."))

	def validate_tiers(self):
		names, ranks = set(), set()
		for tier in self.tiers or []:
			if tier.tier_name in names:
				frappe.throw(_("Tier {0} appears twice.").format(tier.tier_name))
			if cint(tier.rank) in ranks:
				frappe.throw(_("Two tiers share rank {0}.").format(tier.rank))
			names.add(tier.tier_name)
			ranks.add(cint(tier.rank))
			if flt(tier.earn_multiplier) <= 0:
				tier.earn_multiplier = 1

	def validate_single_active(self):
		if self.status != "Active":
			return
		other = frappe.db.get_value(
			self.doctype, {"company": self.company, "status": "Active", "name": ["!=", self.name]}, "name"
		)
		if other:
			frappe.throw(_("Programme {0} is already Active for {1}. Pause or end it first.").format(other, self.company))

	def on_update(self):
		from excel_restaurant_pos.shared.loyalty.campaigns import bust_cache

		bust_cache(self.name)
		frappe.enqueue(
			"excel_restaurant_pos.shared.loyalty.wallet.sync.sync_programme",
			queue="short",
			enqueue_after_commit=True,
			programme=self.name,
		)
