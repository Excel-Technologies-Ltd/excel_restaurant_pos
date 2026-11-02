"""Shared plumbing for the loyalty endpoints: who is calling, and the account summary."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from excel_restaurant_pos.shared.customer_access import is_staff, own_customer_or_refuse, require_login
from excel_restaurant_pos.shared.loyalty.accounts import account_for_customer, member_token
from excel_restaurant_pos.shared.loyalty.settings import (
	ACCOUNT,
	LOYALTY_MANAGER,
	WALLET_PASS,
	get_active_programme,
	get_programme,
	get_settings,
	is_enabled,
)

STAFF_ROLES = (
	"System Manager",
	LOYALTY_MANAGER,
	"ArcPOS Manager",
	"ArcPOS Register User",
	"Restaurant Manager",
	"Restaurant Cashier",
	"Restaurant Waiter",
)


def require_enabled():
	if not is_enabled() or not get_active_programme():
		frappe.throw(_("The loyalty programme is not available right now."), frappe.ValidationError)


def require_staff() -> str:
	user = require_login()
	if user == "Administrator":
		return user
	if not is_staff(user) or not set(frappe.get_roles(user)) & set(STAFF_ROLES):
		frappe.throw(_("You are not permitted to manage loyalty points."), frappe.PermissionError)
	return user


def own_account(required: bool = True) -> tuple[str, str | None]:
	"""The caller's Customer and loyalty account, decided by the server from the session."""
	user = require_login()
	customer = own_customer_or_refuse(user)
	account = account_for_customer(customer)
	if required and not account:
		frappe.throw(_("You are not a loyalty member yet."), frappe.DoesNotExistError)
	return customer, account


def account_summary(account_name: str, include_token: bool = True) -> dict:
	from excel_restaurant_pos.shared.loyalty.tiers import progress

	account = frappe.get_doc(ACCOUNT, account_name)
	programme = get_programme(account.programme)
	settings = get_settings()
	point_value = flt(programme.point_value) if programme else 0
	currency = frappe.get_cached_value("Company", programme.company, "default_currency") if programme else None
	passes = frappe.get_all(WALLET_PASS, filters={"account": account.name}, fields=["platform", "status"])

	data = {
		"member_number": account.member_number,
		"status": account.status,
		"customer_name": account.customer_name,
		"enrolled_on": account.enrolled_on,
		"tier": account.tier,
		"tier_since": account.tier_since,
		"tier_progress": progress(account, programme) if programme else None,
		"available_points": cint(account.available_points),
		"available_value": flt(cint(account.available_points) * point_value, 2),
		"pending_points": cint(account.pending_points),
		"pending_value": flt(cint(account.pending_points) * point_value, 2),
		"expiring": (
			{"date": account.next_expiry_date, "points": cint(account.next_expiry_points)}
			if account.next_expiry_date
			else None
		),
		"lifetime": {
			"earned": cint(account.lifetime_earned),
			"redeemed": cint(account.lifetime_redeemed),
			"expired": cint(account.lifetime_expired),
		},
		"preferences": {"notify_email": cint(account.notify_email), "notify_push": cint(account.notify_push)},
		"wallet": {
			"google": next((p.status for p in passes if p.platform == "Google"), None),
			"apple": next((p.status for p in passes if p.platform == "Apple"), None),
			"google_enabled": bool(settings and cint(settings.google_enabled)),
			"apple_enabled": bool(settings and cint(settings.apple_enabled)),
		},
		"programme": {
			"name": (settings.programme_display_name if settings else None)
			or (programme.programme_name if programme else None),
			"point_value": point_value,
			"currency": currency,
			"terms": programme.terms if programme else None,
		},
	}
	if include_token and account.status == "Active":
		data["member_token"] = member_token(account)
	return data


def load_invoice(name: str):
	if not name:
		frappe.throw(_("sales_invoice is required."), frappe.ValidationError)
	if not frappe.db.exists("Sales Invoice", name):
		frappe.throw(_("Order not found"), frappe.DoesNotExistError)
	return frappe.get_doc("Sales Invoice", name)
