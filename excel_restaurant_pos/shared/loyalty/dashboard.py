"""Number cards for the Loyalty workspace."""

import frappe
from frappe.utils import cint, flt, get_first_day, nowdate

from excel_restaurant_pos.shared.loyalty.accounting import outstanding_points as _outstanding
from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, CAMPAIGN, TXN, get_programme, get_settings


def _guard():
	if not frappe.has_permission(TXN, "read"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)


def _programme():
	settings = get_settings()
	return get_programme(settings.active_programme) if settings else None


def _month_sum(types: tuple, sign: int = 1) -> int:
	row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(points), 0) FROM `tab{TXN}`
		WHERE transaction_type IN %(types)s AND posting_datetime >= %(start)s
		""",
		{"types": types, "start": get_first_day(nowdate())},
	)
	return cint(row[0][0]) * sign


@frappe.whitelist()
def active_members(filters=None):
	_guard()
	return {"value": frappe.db.count(ACCOUNT, {"status": "Active"}), "fieldtype": "Int"}


@frappe.whitelist()
def outstanding_points(filters=None):
	_guard()
	programme = _programme()
	return {"value": _outstanding(programme.name) if programme else 0, "fieldtype": "Int"}


@frappe.whitelist()
def outstanding_liability(filters=None):
	_guard()
	programme = _programme()
	if not programme:
		return {"value": 0, "fieldtype": "Currency"}
	currency = frappe.get_cached_value("Company", programme.company, "default_currency")
	value = flt(_outstanding(programme.name) * flt(programme.point_value), 2)
	return {"value": value, "fieldtype": "Currency", "currency": currency}


@frappe.whitelist()
def earned_this_month(filters=None):
	_guard()
	return {"value": _month_sum(("Earn", "Bonus")), "fieldtype": "Int"}


@frappe.whitelist()
def redeemed_this_month(filters=None):
	_guard()
	return {"value": _month_sum(("Redeem",), -1), "fieldtype": "Int"}


@frappe.whitelist()
def expired_this_month(filters=None):
	_guard()
	return {"value": _month_sum(("Expire",), -1), "fieldtype": "Int"}


@frappe.whitelist()
def active_campaigns(filters=None):
	_guard()
	return {"value": frappe.db.count(CAMPAIGN, {"status": "Active"}), "fieldtype": "Int"}
