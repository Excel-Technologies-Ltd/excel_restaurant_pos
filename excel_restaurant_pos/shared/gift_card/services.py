"""Gift card generation, activation, balance, and sales-invoice hooks."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from excel_restaurant_pos.shared.coupon.services import (
	COUPON_STATUS_ACTIVE,
	COUPON_STATUS_EXPIRED,
	COUPON_STATUS_USED,
	generate_unique_coupon_code,
	get_coupon_settings,
	normalize_channel,
	normalize_coupon_name,
)
from excel_restaurant_pos.shared.gift_card.validation import (
	GIFT_CARD_TYPE,
	GIFT_CARD_TYPE_EXISTING,
	GIFT_CARD_TYPE_NEW,
	assert_inactive_gift_card,
	get_gift_card_lines,
	resolve_line_gift_amount,
)

# Generation checkbox → channel pairs (same model as promotional coupons)
_GENERATION_FLAG_PAIRS = {
	"dine_in_by_sales": {("table", "dine-in"), ("table", "takeout")},
	"in_store_pickup_by_sales": {("in store", "pickup")},
	"online_delivery_by_sales": {("website", "delivery")},
	"online_pickup_by_sales": {("website", "pickup")},
}

_REDEMPTION_FLAG_PAIRS = {
	"dine_in_gift_redeem": {("table", "dine-in"), ("table", "takeout")},
	"in_store_pickup_gift_redeem": {("in store", "pickup")},
	"online_delivery_gift_redeem": {("website", "delivery")},
	"online_pickup_gift_redeem": {("website", "pickup")},
}


def get_gift_card_settings():
	"""Return ArcPOS Settings for gift card operations."""
	return get_coupon_settings()


def _channel_matches_flags(doc, flag_pairs: dict[str, set], settings) -> bool:
	channel = normalize_channel(doc.get("custom_order_from"), doc.get("custom_service_type"))
	for flag_name, pairs in flag_pairs.items():
		if cint(getattr(settings, flag_name, 0)) and channel in pairs:
			return True
	return False


def is_gift_card_generation_allowed(doc, settings=None) -> bool:
	"""True when invoice channel may sell/generate gift cards."""
	settings = settings or get_gift_card_settings()
	if not settings:
		return False
	if cint(settings.no_by_sales):
		return False
	return _channel_matches_flags(doc, _GENERATION_FLAG_PAIRS, settings)


def is_gift_card_redemption_channel_allowed(doc, settings=None) -> bool:
	"""True when invoice channel may redeem gift cards."""
	settings = settings or get_gift_card_settings()
	if not settings:
		return False
	return _channel_matches_flags(doc, _REDEMPTION_FLAG_PAIRS, settings)


def get_gift_card_email(doc) -> str:
	"""Resolve email for gift cards sold on this invoice."""
	explicit = (doc.get("custom_gift_cards_for") or "").strip()
	if explicit:
		return explicit

	customer = doc.get("customer")
	if customer:
		try:
			from excel_restaurant_pos.shared.contacts.get_customer_emails import get_customer_emails

			for email in get_customer_emails(customer):
				if cint(email.get("is_primary")):
					return (email.get("email_id") or "").strip()
		except Exception:
			pass
		customer_email = frappe.db.get_value("Customer", customer, "email_id")
		if customer_email:
			return customer_email.strip()

	return (doc.get("custom_email_address") or "").strip()


def _validate_gift_pricing_rule(settings) -> str:
	pricing_rule = (getattr(settings, "default_pricing_rule_gift", None) or "").strip()
	if not pricing_rule:
		frappe.throw(
			_("Please set Default Pricing Rule (Gift) in ArcPOS Settings before selling gift cards."),
			frappe.MandatoryError,
		)
	if not frappe.db.exists("Pricing Rule", pricing_rule):
		frappe.throw(
			_("Default Pricing Rule (Gift) {0} does not exist. Please update ArcPOS Settings.").format(
				pricing_rule
			),
			frappe.DoesNotExistError,
		)
	return pricing_rule


def _gift_validity_dates(settings, posting_date=None) -> tuple[Any, Any]:
	valid_from = getdate(posting_date or nowdate())
	expire_after = cint(getattr(settings, "expire_after_days_gift", 0) or 0)
	if not expire_after:
		frappe.throw(
			_("Expire After (Days) for Gift Cards is required in ArcPOS Settings."),
			frappe.MandatoryError,
		)
	return valid_from, add_days(valid_from, expire_after)


def _resolve_gift_card_customer(invoice=None) -> str:
	"""Resolve Customer link required by ERPNext for Gift Card coupons."""
	if invoice:
		customer = (invoice.get("customer") or "").strip()
		if customer:
			return customer

	settings = get_gift_card_settings()
	customer = (getattr(settings, "customer", None) or "").strip() if settings else ""
	if customer:
		return customer

	frappe.throw(
		_("Customer is required to sell gift cards. Set a customer on the invoice or Default Customer in ArcPOS Settings."),
		frappe.MandatoryError,
	)


def create_gift_card_coupon(invoice, amount: float, settings, defer_invoice_link: bool = True) -> Any:
	"""Create an Active Gift Card Coupon Code on invoice submit (type=New)."""
	pricing_rule = _validate_gift_pricing_rule(settings)
	prefix = (getattr(settings, "gift_card_prefix", None) or "GIFT####").strip()
	coupon_code = generate_unique_coupon_code(prefix)
	valid_from, valid_upto = _gift_validity_dates(settings, invoice.get("posting_date"))
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Gift Card amount must be greater than zero."))

	fields = {
		"customer": _resolve_gift_card_customer(invoice),
		"doctype": "Coupon Code",
		"name": coupon_code,
		"coupon_name": coupon_code,
		"coupon_code": coupon_code,
		"coupon_type": GIFT_CARD_TYPE,
		"pricing_rule": pricing_rule,
		"valid_from": valid_from,
		"valid_upto": valid_upto,
		"maximum_use": 0,
		"used": 0,
		"custom_discount_type": "Flat Amount",
		"custom_discount_amount": amount,
		"custom_available_balance": amount,
		"custom_created_on": now_datetime(),
		"custom_linked_email": get_gift_card_email(invoice),
		"custom_status": COUPON_STATUS_ACTIVE,
		"custom_order_status": 1,
	}
	# Defer invoice link during before_submit to avoid LinkValidationError.
	if not defer_invoice_link and invoice and invoice.get("name"):
		fields["custom_generated_on_order"] = invoice.name

	coupon = frappe.get_doc(fields)
	if invoice and invoice.get("name"):
		coupon.flags.generated_for_invoice = invoice.name
	coupon.insert(ignore_permissions=True)
	return coupon


def activate_existing_gift_card(coupon, invoice, settings) -> Any:
	"""Activate an Inactive gift card on invoice submit (type=Existing)."""
	if isinstance(coupon, str):
		coupon = frappe.get_doc("Coupon Code", coupon)

	valid_from, valid_upto = _gift_validity_dates(settings, invoice.get("posting_date"))
	face_value = flt(coupon.custom_discount_amount)
	if face_value <= 0:
		frappe.throw(_("Gift Card {0} has no face value.").format(coupon.name))

	coupon.custom_status = COUPON_STATUS_ACTIVE
	coupon.custom_order_status = 1
	coupon.valid_from = valid_from
	coupon.valid_upto = valid_upto
	coupon.custom_available_balance = face_value
	coupon.custom_linked_email = get_gift_card_email(invoice) or coupon.custom_linked_email
	coupon.customer = _resolve_gift_card_customer(invoice)
	coupon.custom_generated_on_order = invoice.name
	coupon.custom_discount_type = coupon.custom_discount_type or "Flat Amount"
	coupon.save(ignore_permissions=True)
	return coupon


def recompute_available_balance(coupon_doc_or_name, save: bool = True) -> float:
	"""Recompute balance from redemption log; mark Used when depleted."""
	coupon = (
		frappe.get_doc("Coupon Code", coupon_doc_or_name)
		if isinstance(coupon_doc_or_name, str)
		else coupon_doc_or_name
	)

	redeemed = sum(flt(row.redeemed_amount) for row in (coupon.get("custom_coupon_redeemed_on_orders") or []))
	balance = flt(coupon.custom_discount_amount) - redeemed
	if balance < 0:
		balance = 0.0

	coupon.custom_available_balance = balance

	status = (coupon.custom_status or "").strip()
	if status not in ("Rejected", COUPON_STATUS_EXPIRED):
		if balance <= 0:
			coupon.custom_status = COUPON_STATUS_USED
		elif status == COUPON_STATUS_USED and balance > 0:
			coupon.custom_status = COUPON_STATUS_ACTIVE

	if save:
		coupon.save(ignore_permissions=True)

	return balance


def validate_gift_card_lines(doc, method=None):
	"""Validate gift card item lines on Sales Invoice (draft-safe)."""
	lines = get_gift_card_lines(doc)
	if not lines:
		return

	seen_existing: set[str] = set()

	for line in lines:
		gift_type = (line.get("custom_gift_card_type") or "").strip()
		if gift_type not in (GIFT_CARD_TYPE_NEW, GIFT_CARD_TYPE_EXISTING):
			frappe.throw(
				_("Gift Card Type (New or Existing) is required for item {0}.").format(
					line.get("item_code") or line.idx
				)
			)

		if gift_type == GIFT_CARD_TYPE_NEW:
			amount = resolve_line_gift_amount(line)
			if amount <= 0:
				frappe.throw(
					_(
						"Gift Card Value is required for item {0}. Set custom_gift_card_value on the Item."
					).format(line.get("item_code"))
				)
			line.custom_gift_amount = amount
			continue

		code = (line.get("custom_gift_card_code") or "").strip()
		if not code:
			frappe.throw(
				_("Gift Card Code is required when Gift Card Type is Existing (item {0}).").format(
					line.get("item_code")
				)
			)

		coupon = assert_inactive_gift_card(code, for_submit=False)
		coupon_name = coupon.name
		if coupon_name in seen_existing:
			frappe.throw(_("Gift Card {0} is selected more than once on this invoice.").format(coupon_name))
		seen_existing.add(coupon_name)

		amount = flt(coupon.custom_discount_amount)
		line.custom_gift_amount = amount
		line.custom_coupon_value = amount


def process_gift_cards_on_submit(doc, method=None):
	"""Create New / activate Existing gift cards on Sales Invoice submit."""
	lines = get_gift_card_lines(doc)
	if not lines:
		return

	settings = get_gift_card_settings()
	if not settings:
		frappe.throw(_("ArcPOS Settings is required before selling gift cards."))

	if not is_gift_card_generation_allowed(doc, settings):
		frappe.throw(
			_("Gift card sales are not allowed for this order type. Check ArcPOS Settings.")
		)

	existing_codes = [
		c.strip() for c in (doc.get("custom_generated_gift_cards") or "").split(",") if c.strip()
	]
	if existing_codes:
		return

	generated: list[str] = []

	for line in lines:
		gift_type = (line.get("custom_gift_card_type") or "").strip()
		qty = max(cint(line.get("qty")) or 1, 1)

		if gift_type == GIFT_CARD_TYPE_NEW:
			amount = resolve_line_gift_amount(line)
			for __ in range(qty):
				coupon = create_gift_card_coupon(doc, amount, settings)
				generated.append(coupon.name)
			continue

		if qty != 1:
			frappe.throw(
				_("Existing gift card lines must have quantity 1 (item {0}).").format(line.get("item_code"))
			)
		coupon = assert_inactive_gift_card(line.get("custom_gift_card_code"), for_submit=True)
		activate_existing_gift_card(coupon, doc, settings)
		generated.append(coupon.name)

	doc.custom_generated_gift_cards = ", ".join(generated)
	email = get_gift_card_email(doc)
	if email and not (doc.get("custom_gift_cards_for") or "").strip():
		doc.custom_gift_cards_for = email


def finalize_gift_card_links(doc, method=None):
	"""Persist generated gift card codes and email after submit."""
	codes = (doc.get("custom_generated_gift_cards") or "").strip()
	if not codes:
		return

	values = {"custom_generated_gift_cards": codes}
	email = (doc.get("custom_gift_cards_for") or "").strip() or get_gift_card_email(doc)
	if email:
		values["custom_gift_cards_for"] = email

	frappe.db.set_value("Sales Invoice", doc.name, values, update_modified=False)

	for code in [c.strip() for c in codes.split(",") if c.strip()]:
		if not frappe.db.exists("Coupon Code", code):
			continue
		updates = {"custom_generated_on_order": doc.name, "custom_order_status": 1}
		if email:
			updates["custom_linked_email"] = email
		frappe.db.set_value("Coupon Code", code, updates, update_modified=False)


def record_gift_card_redemptions(doc, method=None):
	"""Log each applied gift card redemption and recompute balances."""
	applied = doc.get("custom_applied_gift_cards") or []
	if not applied:
		return

	if not is_gift_card_redemption_channel_allowed(doc):
		frappe.throw(_("Gift card redemption is not allowed for this order type."))

	promo = normalize_coupon_name(doc.get("custom_coupon_code"))
	if promo:
		promo_type = frappe.db.get_value("Coupon Code", promo, "coupon_type")
		if (promo_type or "").strip() != GIFT_CARD_TYPE:
			frappe.throw(_("Cannot redeem gift cards together with a promotional coupon."))

	seen: set[str] = set()
	for row in applied:
		code = normalize_coupon_name(row.get("gift_card_code"))
		amount = flt(row.get("redeemed_amount"))
		if not code or amount <= 0:
			frappe.throw(_("Each applied gift card must have a code and redeemed amount."))

		if code in seen:
			frappe.throw(_("Gift Card {0} is applied more than once.").format(code))
		seen.add(code)

		coupon = frappe.get_doc("Coupon Code", code)
		if (coupon.coupon_type or "").strip() != GIFT_CARD_TYPE:
			frappe.throw(_("Coupon {0} is not a Gift Card.").format(code))

		if coupon.custom_generated_on_order == doc.name:
			frappe.throw(_("Cannot redeem gift card {0} on the invoice that sold it.").format(code))

		status = (coupon.custom_status or "").strip()
		if status != COUPON_STATUS_ACTIVE:
			frappe.throw(_("Gift Card {0} is {1}.").format(code, status.lower() or _("invalid")))

		posting_date = getdate(doc.get("posting_date") or nowdate())
		if coupon.valid_upto and posting_date > getdate(coupon.valid_upto):
			coupon.custom_status = COUPON_STATUS_EXPIRED
			coupon.save(ignore_permissions=True)
			frappe.throw(_("Gift Card {0} has expired.").format(code))

		balance = flt(coupon.custom_available_balance)
		if amount > balance + 0.0001:
			frappe.throw(
				_("Gift Card {0} has insufficient balance ({1}).").format(
					code, frappe.format_value(balance, {"fieldtype": "Currency"})
				)
			)

		already = any(
			(r.sales_invoice == doc.name and flt(r.redeemed_amount) == amount)
			for r in (coupon.get("custom_coupon_redeemed_on_orders") or [])
		)
		if not already:
			coupon.append(
				"custom_coupon_redeemed_on_orders",
				{"sales_invoice": doc.name, "redeemed_amount": amount},
			)

		recompute_available_balance(coupon, save=True)
