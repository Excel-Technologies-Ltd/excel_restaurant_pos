# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from excel_restaurant_pos.shared.loyalty import accounts, ledger
from excel_restaurant_pos.shared.loyalty.settings import LOYALTY_MANAGER, TXN, get_active_programme, is_excluded_customer

MANAGERS = [LOYALTY_MANAGER, "System Manager"]


class ArcPOSLoyaltyAccount(Document):
	def autoname(self):
		self.member_number = self.member_number or accounts.generate_member_number()
		self.name = self.member_number

	def validate(self):
		if self.is_new():
			if is_excluded_customer(self.customer):
				frappe.throw(_("Customer {0} is excluded from the loyalty programme.").format(self.customer))
			if not self.programme:
				programme = get_active_programme()
				self.programme = programme.name if programme else None
			self.enrolled_on = self.enrolled_on or now_datetime()
			self.user = self.user or accounts.user_for_customer(self.customer)
			return

		before = self.get_doc_before_save()
		if before and before.status != self.status and not self.flags.status_via_service:
			frappe.throw(_("Use the Suspend, Reactivate or Close actions to change the status."))

	def on_trash(self):
		if frappe.db.exists(TXN, {"account": self.name}):
			frappe.throw(_("A loyalty account with ledger entries cannot be deleted. Close it instead."))


@frappe.whitelist(methods=["POST"])
def recompute_balance(account):
	frappe.only_for(MANAGERS)
	return ledger.recompute_cache(account)


@frappe.whitelist(methods=["POST"])
def change_status(account, status, remarks=None):
	frappe.only_for(MANAGERS)
	accounts.set_status(account, status, remarks)
	return frappe.db.get_value("ArcPOS Loyalty Account", account, "status")


@frappe.whitelist(methods=["POST"])
def reissue(account):
	frappe.only_for(MANAGERS + ["Restaurant Manager", "ArcPOS Manager"])
	accounts.reissue_token(account)
	return True
