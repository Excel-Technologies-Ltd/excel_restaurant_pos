"""Event-based points: emit(event_code, customer) and the built-in emitters."""

from __future__ import annotations

import calendar

import frappe
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate

from excel_restaurant_pos.shared.loyalty import campaigns, ledger, rules
from excel_restaurant_pos.shared.loyalty.accounts import account_for_customer
from excel_restaurant_pos.shared.loyalty.earning import WEEKDAYS, expiry_for, member_context, safely
from excel_restaurant_pos.shared.loyalty.settings import (
	ACCOUNT,
	EVENT_TYPE,
	TXN,
	get_active_programme,
	is_enabled,
	is_excluded_customer,
)

BUILTIN_EVENTS = {
	"customer_signup": {"description": "A storefront account was created.", "once_per_customer": 1},
	"first_order": {"description": "The customer's first paid order.", "once_per_customer": 1},
	"birthday": {"description": "The customer's birthday (Customer Date of Birth).", "cooldown_days": 300},
	"feedback_submitted": {"description": "The customer completed order feedback."},
	"referral": {"description": "A referred friend joined (fired through the events API)."},
}
BIRTHDAY_FIELD = "custom_date_of_birth"


def ensure_builtin_event_types():
	if not frappe.db.table_exists(EVENT_TYPE):
		return
	for code, values in BUILTIN_EVENTS.items():
		if frappe.db.exists(EVENT_TYPE, code):
			continue
		frappe.get_doc({"doctype": EVENT_TYPE, "event_code": code, "enabled": 1, "is_builtin": 1, **values}).insert(
			ignore_permissions=True
		)


def _blocked_by_frequency(account: str, event_type) -> bool:
	if cint(event_type.once_per_customer):
		if frappe.db.exists(TXN, {"account": account, "event_type": event_type.name, "points": [">", 0]}):
			return True
	cooldown = cint(event_type.cooldown_days)
	if cooldown:
		last = frappe.db.get_value(
			TXN,
			{"account": account, "event_type": event_type.name, "points": [">", 0]},
			"posting_datetime",
			order_by="posting_datetime desc",
		)
		if last and get_datetime(last) > add_days(now_datetime(), -cooldown):
			return True
	return False


def emit(
	event_code: str,
	customer: str,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	payload: dict | None = None,
	reference_key: str | None = None,
) -> list[str]:
	"""Award the points configured for an event. Idempotent per (event, customer, reference).

	`reference_key` (or the reference document, or today's date when neither
	is given) makes the idempotency key, so a retried emitter awards once.
	"""
	if not is_enabled() or not customer or is_excluded_customer(customer):
		return []
	programme = get_active_programme()
	if not programme:
		return []
	try:
		event_type = frappe.get_cached_doc(EVENT_TYPE, event_code)
	except frappe.DoesNotExistError:
		return []
	if not cint(event_type.enabled):
		return []

	account = account_for_customer(customer)
	if not account:
		return []
	locked = ledger.lock_account(account)
	reference = reference_key or reference_name or nowdate()
	key_prefix = f"event:{event_code}:{customer}:{reference}:"
	if ledger.find_by_key_prefix(key_prefix):
		return ledger.find_by_key_prefix(key_prefix)
	if locked.status != "Active" or _blocked_by_frequency(account, event_type):
		return []

	payload = payload or {}
	now = now_datetime()
	ctx = {
		"kind": "event",
		"event_code": event_code,
		"payload": payload,
		"customer": customer,
		"channel": None,
		"territory": frappe.db.get_value("Customer", customer, "territory"),
		"posting_datetime": now,
		"weekday": WEEKDAYS[now.weekday()],
		"hour": now.hour,
		"order_number": 0,
		"lines": [],
		"eligible_amount": flt(payload.get("amount")),
		"total": flt(payload.get("amount")),
		**member_context(account, programme),
	}
	chosen = campaigns.select_for_context(programme.name, ctx)
	scopes = [rules.base_scope(programme), *[rules.campaign_scope(c) for c in chosen]]
	awards = rules.evaluate(ctx, scopes, tier_multiplier=1, rounding=programme.points_rounding or "Floor")

	expiry = expiry_for(programme, nowdate())
	names, total = [], 0
	for award in awards:
		points = campaigns.capped_points(award.get("campaign"), account, award["points"])
		if points <= 0:
			continue
		name, created = ledger.post_credit(
			locked,
			"Bonus",
			points,
			f"{key_prefix}{award['scope']}:{award['rule_id']}",
			expiry_date=expiry,
			source_doctype=reference_doctype if reference_name else "Customer",
			source_name=reference_name if reference_name else customer,
			campaign=award.get("campaign"),
			rule_id=award.get("rule_id"),
			event_type=event_code,
			remarks=award.get("rule_name"),
		)
		if name:
			names.append(name)
			total += points if created else 0
			if award.get("campaign"):
				campaigns.update_stats(award["campaign"])

	if names:
		ledger.recompute_cache(account, touch_activity=True)
	if total:
		from excel_restaurant_pos.shared.loyalty.notifications import enqueue_notification

		enqueue_notification(
			account,
			"earned",
			key=f"earned:{key_prefix}",
			context={"points": total, "event": event_code},
		)
	return names


# ---------------------------------------------------------------- built-in emitters


def on_feedback_update(doc, method=None):
	"""ArcPOS Feedback on_update: feedback rows are created at submit and completed later."""
	if not is_enabled() or doc.get("is_completed") != "Yes":
		return
	before = doc.get_doc_before_save()
	if before and before.get("is_completed") == "Yes":
		return
	customer = doc.get("feedback_by_member") or (
		frappe.db.get_value("Sales Invoice", doc.sales_invoice_no, "customer") if doc.get("sales_invoice_no") else None
	)
	if customer:
		safely(
			"Loyalty feedback event failed",
			emit,
			"feedback_submitted",
			customer,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)


def birthday_days(today) -> list[int]:
	"""The days of `today`'s month whose birthdays are celebrated today."""
	days = [today.day]
	if (today.month, today.day) == (2, 28) and not calendar.isleap(today.year):
		# No Feb 29 this year: those members celebrate on the 28th.
		days.append(29)
	return days


def award_birthdays():
	"""Daily: members whose Customer Date of Birth falls today."""
	if not is_enabled() or not get_active_programme():
		return
	if not frappe.get_meta("Customer").has_field(BIRTHDAY_FIELD):
		return
	today = getdate(nowdate())
	days = birthday_days(today)
	customers = frappe.db.sql(
		f"""
		SELECT c.name
		FROM `tabCustomer` c
		JOIN `tab{ACCOUNT}` a ON a.customer = c.name AND a.status = 'Active'
		WHERE MONTH(c.{BIRTHDAY_FIELD}) = %s AND DAY(c.{BIRTHDAY_FIELD}) IN %s
		""",
		(today.month, tuple(days)),
		pluck=True,
	)
	for customer in customers:
		safely(
			"Loyalty birthday award failed",
			emit,
			"birthday",
			customer,
			reference_doctype="Customer",
			reference_name=customer,
			reference_key=f"birthday-{today.year}",
		)
		frappe.db.commit()
