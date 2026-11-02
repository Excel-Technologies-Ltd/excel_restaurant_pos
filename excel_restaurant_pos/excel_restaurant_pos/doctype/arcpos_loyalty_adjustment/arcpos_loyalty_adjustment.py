# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime, nowdate

from excel_restaurant_pos.shared.loyalty import ledger
from excel_restaurant_pos.shared.loyalty.earning import expiry_for
from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, LOYALTY_MANAGER, get_programme, get_settings

APPROVERS = (LOYALTY_MANAGER, "System Manager")


def is_approver(user=None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(APPROVERS))


class ArcPOSLoyaltyAdjustment(Document):
	"""Manual points correction. Above the settings threshold it needs a Loyalty Manager."""

	def validate(self):
		if not cint(self.points):
			frappe.throw(_("Points cannot be zero."))
		status = frappe.db.get_value(ACCOUNT, self.account, "status")
		if status == "Closed":
			frappe.throw(_("Loyalty account {0} is closed.").format(self.account))
		if self.expiry_date and cint(self.points) < 0:
			self.expiry_date = None

		threshold = cint(get_settings().adjustment_approval_threshold)
		self.requires_approval = 1 if threshold and abs(cint(self.points)) > threshold else 0
		if self.is_new():
			self.requested_by = frappe.session.user
			# Set by the approval flow only, never by whoever creates the row.
			self.approval_status = None
			self.approved_by = self.approved_on = None
		if self.approval_status in (None, "", "Draft", "Pending Approval"):
			self.approval_status = "Pending Approval" if self.requires_approval or not is_approver() else "Draft"

	def before_submit(self):
		if not is_approver():
			frappe.throw(_("Only a Loyalty Manager can post an adjustment."), frappe.PermissionError)
		if self.requires_approval and self.approval_status != "Approved":
			frappe.throw(_("This adjustment needs approval before it is posted."))
		# Four eyes: an adjustment large enough to need approval is approved by
		# someone other than whoever asked for it (System Manager excepted).
		if (
			self.requires_approval
			and self.requested_by == frappe.session.user
			and "System Manager" not in frappe.get_roles()
			and frappe.session.user != "Administrator"
		):
			frappe.throw(
				_("Another Loyalty Manager must approve an adjustment you requested."), frappe.PermissionError
			)
		if self.approval_status != "Approved":
			self.approval_status = "Approved"
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()

	def on_submit(self):
		locked = ledger.lock_account(self.account)
		programme = get_programme(locked.programme)
		fields = {"source_doctype": self.doctype, "source_name": self.name, "remarks": f"{self.reason}: {self.remarks}"}
		if cint(self.points) > 0:
			name, _created = ledger.post_credit(
				locked,
				"Adjust",
				cint(self.points),
				f"adjust:{self.name}",
				expiry_date=self.expiry_date or (expiry_for(programme, nowdate()) if programme else None),
				**fields,
			)
		else:
			name, _created = ledger.post_debit(locked, "Adjust", -cint(self.points), f"adjust:{self.name}", allow_negative=True, **fields)
		self.db_set("transaction", name)
		ledger.recompute_cache(self.account, touch_activity=True)

	def on_cancel(self):
		if not self.transaction:
			return
		locked = ledger.lock_account(self.account)
		programme = get_programme(locked.programme)
		fields = {"source_doctype": self.doctype, "source_name": self.name}
		if cint(self.points) > 0:
			ledger.reverse_credit(
				locked,
				self.transaction,
				f"adjust-cancel:{self.name}",
				allow_negative=cint(programme.allow_negative_balance_on_reversal) if programme else 0,
				**fields,
			)
		else:
			ledger.restore_debit(locked, self.transaction, f"adjust-cancel:{self.name}", **fields)
		ledger.recompute_cache(self.account)


def _decide(name):
	if not is_approver():
		frappe.throw(_("Only a Loyalty Manager can decide on adjustments."), frappe.PermissionError)
	doc = frappe.get_doc("ArcPOS Loyalty Adjustment", name)
	if doc.docstatus != 0:
		frappe.throw(_("This adjustment was already decided."))
	return doc


@frappe.whitelist(methods=["POST"])
def approve(name):
	doc = _decide(name)
	doc.approval_status = "Approved"
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.submit()
	return doc.name


@frappe.whitelist(methods=["POST"])
def reject(name, reason=None):
	doc = _decide(name)
	doc.approval_status = "Rejected"
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.rejection_reason = reason
	doc.save()
	return doc.name
