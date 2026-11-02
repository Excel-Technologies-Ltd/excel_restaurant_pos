"""Segments: which members a campaign targets. Evaluated on demand, cached 1 h."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime

from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, SEGMENT

CACHE_TTL = 3600
VERSION_KEY = "loyalty:segments:version"


def _version() -> int:
	return cint(frappe.cache().get_value(VERSION_KEY)) or 0


def bust_cache():
	"""Called when any segment changes: old per-account entries stop being read."""
	frappe.cache().set_value(VERSION_KEY, _version() + 1)


def lifetime_spend(customer: str) -> float:
	row = frappe.db.sql(
		"SELECT COALESCE(SUM(base_net_total), 0) FROM `tabSales Invoice` WHERE customer = %s AND docstatus = 1",
		customer,
	)
	return flt(row[0][0])


def _member_info(account) -> frappe._dict:
	customer = frappe.db.get_value("Customer", account.customer, ["customer_group", "territory"], as_dict=True) or {}
	return frappe._dict(
		customer_group=customer.get("customer_group"),
		territory=customer.get("territory"),
		tier=account.tier,
		enrolled_on=account.enrolled_on,
		order_count=cint(account.order_count),
		last_order_at=account.last_order_at,
		lifetime_spend=None,
	)


def is_descendant(doctype, value, ancestor) -> bool:
	"""Whether `value` is `ancestor` or below it in a tree doctype."""
	if not value or not ancestor:
		return False
	if value == ancestor:
		return True
	bounds = frappe.db.get_value(doctype, ancestor, ["lft", "rgt"], as_dict=True)
	node = frappe.db.get_value(doctype, value, ["lft", "rgt"], as_dict=True)
	return bool(bounds and node and bounds.lft <= node.lft and node.rgt <= bounds.rgt)


def filters_match(segment, info, customer) -> bool:
	if segment.customer_group and not is_descendant("Customer Group", info.customer_group, segment.customer_group):
		return False
	if segment.territory and not is_descendant("Territory", info.territory, segment.territory):
		return False
	if segment.tier and info.tier != segment.tier:
		return False
	enrolled = getdate(info.enrolled_on) if info.enrolled_on else None
	if segment.enrolled_from and (not enrolled or enrolled < getdate(segment.enrolled_from)):
		return False
	if segment.enrolled_to and (not enrolled or enrolled > getdate(segment.enrolled_to)):
		return False
	if cint(segment.min_orders) and info.order_count < cint(segment.min_orders):
		return False
	if cint(segment.max_orders) and info.order_count > cint(segment.max_orders):
		return False
	if cint(segment.last_order_within_days):
		since = add_days(now_datetime(), -cint(segment.last_order_within_days))
		if not info.last_order_at or get_datetime(info.last_order_at) < since:
			return False
	if flt(segment.min_lifetime_spend):
		if info.lifetime_spend is None:
			info.lifetime_spend = lifetime_spend(customer)
		if info.lifetime_spend < flt(segment.min_lifetime_spend):
			return False
	return True


def segment_matches(segment, account, info=None) -> bool:
	info = info or _member_info(account)
	is_member = any(row.customer == account.customer for row in segment.get("members") or [])
	mode = segment.match_mode or "Filters"
	if mode == "Static Members":
		return is_member
	if mode == "Filters or Static Members" and is_member:
		return True
	return filters_match(segment, info, account.customer)


def account_segments(account_name: str) -> list[str]:
	"""Every segment the account belongs to, cached per account for an hour."""
	key = f"loyalty:segments:{_version()}:{account_name}"
	cached = frappe.cache().get_value(key)
	if cached is not None:
		return list(cached)

	account = frappe.db.get_value(
		ACCOUNT,
		account_name,
		["name", "customer", "tier", "enrolled_on", "order_count", "last_order_at"],
		as_dict=True,
	)
	if not account:
		return []

	info = _member_info(account)
	matched = [
		name
		for name in frappe.get_all(SEGMENT, pluck="name")
		if segment_matches(frappe.get_cached_doc(SEGMENT, name), account, info)
	]

	frappe.cache().set_value(key, matched, expires_in_sec=CACHE_TTL)
	return matched
