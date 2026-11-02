"""POS (staff) loyalty endpoints: member lookup, enrolment, step-up codes, adjustments."""

import frappe
from frappe import _
from frappe.utils import cint

from excel_restaurant_pos.api.loyalty.common import account_summary, load_invoice, require_enabled, require_staff
from excel_restaurant_pos.shared.loyalty import accounts, otp
from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, ADJUSTMENT
from excel_restaurant_pos.utils import rate_limit_by_caller
from excel_restaurant_pos.utils.error_handler import success_response

MAX_MATCHES = 10


def _masked(account_name: str) -> dict:
	summary = account_summary(account_name, include_token=False)
	customer = frappe.db.get_value(ACCOUNT, account_name, "customer")
	contact = frappe.db.get_value("Customer", customer, ["email_id", "mobile_no"], as_dict=True) or {}
	summary["customer"] = customer
	summary["email"] = accounts.mask_email(contact.get("email_id"))
	summary["phone"] = accounts.mask_phone(contact.get("mobile_no"))
	return summary


@frappe.whitelist(methods=["GET"])
def lookup(query=None):
	"""By scanned token, member number, phone or email. Personal details come back masked."""
	require_staff()
	require_enabled()
	rate_limit_by_caller("loyalty_lookup", limit=60, seconds=60)
	matches = accounts.find_accounts(query)[:MAX_MATCHES]
	return success_response(_("Members"), data=[_masked(name) for name in matches])


@frappe.whitelist(methods=["POST"])
def staff_enrol(sales_invoice=None, customer=None):
	require_staff()
	require_enabled()
	if sales_invoice:
		customer = load_invoice(sales_invoice).customer
	if not customer:
		frappe.throw(_("customer or sales_invoice is required."))
	account = accounts.enrol(customer, source="POS")
	if not account:
		frappe.throw(_("Customer {0} cannot join the loyalty programme.").format(customer))
	if sales_invoice and frappe.get_meta("Sales Invoice").has_field("custom_loyalty_account"):
		frappe.db.set_value("Sales Invoice", sales_invoice, "custom_loyalty_account", account, update_modified=False)
	frappe.db.commit()
	return success_response(_("Enrolled"), data=_masked(account))


def _invoice_account(sales_invoice) -> str:
	doc = load_invoice(sales_invoice)
	account = accounts.account_for_customer(doc.customer)
	if not account:
		frappe.throw(_("The order's customer is not a loyalty member."))
	return account


@frappe.whitelist(methods=["POST"])
def request_otp(sales_invoice=None, points=None):
	"""Send the member a code for this many points on this order; the code
	authorises that amount only, and the member sees it in the message."""
	require_staff()
	rate_limit_by_caller("loyalty_request_otp", limit=10, seconds=60)
	result = otp.request(_invoice_account(sales_invoice), sales_invoice, cint(points))
	return success_response(_("Code sent"), data=result)


@frappe.whitelist(methods=["POST"])
def verify_otp(sales_invoice=None, code=None, points=None):
	require_staff()
	rate_limit_by_caller("loyalty_verify_otp", limit=10, seconds=60)
	verified = otp.verify(_invoice_account(sales_invoice), sales_invoice, code, cint(points) or None)
	frappe.db.commit()
	if not verified:
		frappe.throw(_("The code is not correct."), frappe.ValidationError)
	return success_response(_("Verified"), data={"verified": True})


@frappe.whitelist(methods=["POST"])
def adjust(account=None, points=None, reason="Goodwill", remarks=None, expiry_date=None):
	"""Create an adjustment. Posted at once for a Loyalty Manager under the approval threshold."""
	require_staff()
	from excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_adjustment.arcpos_loyalty_adjustment import (
		is_approver,
	)

	if not remarks:
		frappe.throw(_("remarks are required."))
	doc = frappe.get_doc(
		{
			"doctype": ADJUSTMENT,
			"account": account,
			"points": cint(points),
			"reason": reason,
			"remarks": remarks,
			"expiry_date": expiry_date,
		}
	)
	doc.insert()
	if is_approver() and not doc.requires_approval:
		doc.submit()
	frappe.db.commit()
	return success_response(
		_("Adjustment {0}").format(doc.approval_status.lower()),
		data={"adjustment": doc.name, "approval_status": doc.approval_status, "docstatus": doc.docstatus},
	)


@frappe.whitelist(methods=["POST"])
def reissue_pass(account=None):
	# Invalidates the member's barcode and every pass: managers only, the same
	# roles as the Reissue action on the account form.
	from excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_account.arcpos_loyalty_account import (
		MANAGERS,
	)

	require_staff()
	frappe.only_for(MANAGERS + ["Restaurant Manager", "ArcPOS Manager"])
	if not frappe.db.exists(ACCOUNT, account):
		frappe.throw(_("Loyalty account not found."), frappe.DoesNotExistError)
	accounts.reissue_token(account)
	frappe.db.commit()
	return success_response(_("Barcode reissued"), data=_masked(account))
