# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from excel_restaurant_pos.shared.loyalty.settings import LOYALTY_MANAGER, PROGRAMME


class ArcPOSLoyaltySettings(Document):
	def validate(self):
		if not self.get_password("member_token_secret", raise_exception=False):
			self.member_token_secret = frappe.generate_hash(length=48)
		if not self.get_password("google_callback_secret", raise_exception=False):
			self.google_callback_secret = frappe.generate_hash(length=32)

		if cint(self.enabled) and not self.active_programme:
			frappe.throw(_("Choose the Active Programme before enabling loyalty."))
		if self.active_programme:
			status = frappe.db.get_value(PROGRAMME, self.active_programme, "status")
			if status != "Active":
				frappe.msgprint(_("Programme {0} is {1}; nothing is earned or redeemed until it is Active.").format(
					self.active_programme, status
				), alert=True)
		self.validate_accounts()
		self.validate_private_credentials()

	def validate_private_credentials(self):
		"""A private key attached as a public file is served to anyone at /files/."""
		for fieldname in ("google_service_account_json", "apple_pass_certificate", "apple_wwdr_certificate"):
			url = self.get(fieldname) or ""
			if url and not url.startswith("/private/"):
				frappe.throw(
					_("{0} holds a credential: remove it and attach it again with Private ticked.").format(
						self.meta.get_label(fieldname)
					)
				)

	def validate_accounts(self):
		company = frappe.db.get_value(PROGRAMME, self.active_programme, "company") if self.active_programme else None
		for fieldname in ("liability_account", "expense_account"):
			account = self.get(fieldname)
			if account and company and frappe.db.get_value("Account", account, "company") != company:
				frappe.throw(_("{0} must belong to company {1}.").format(self.meta.get_label(fieldname), company))

	def on_update(self):
		self.sync_mode_of_payment_account()

	def sync_mode_of_payment_account(self):
		"""The loyalty tender must post to the liability account."""
		if not (self.loyalty_mode_of_payment and self.liability_account and self.active_programme):
			return
		company = frappe.db.get_value(PROGRAMME, self.active_programme, "company")
		mop = frappe.get_doc("Mode of Payment", self.loyalty_mode_of_payment)
		row = next((r for r in mop.accounts if r.company == company), None)
		if row and row.default_account == self.liability_account:
			return
		if row:
			row.default_account = self.liability_account
		else:
			mop.append("accounts", {"company": company, "default_account": self.liability_account})
		mop.flags.ignore_permissions = True
		mop.save()


@frappe.whitelist(methods=["POST"])
def post_true_up_now():
	frappe.only_for([LOYALTY_MANAGER, "System Manager", "Accounts Manager"])
	from excel_restaurant_pos.shared.loyalty.accounting import post_liability_true_up

	return post_liability_true_up(force=True)
