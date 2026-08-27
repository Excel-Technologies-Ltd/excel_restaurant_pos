"""Gift card redemption: verify, apply, discard, and invoice discount."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from excel_restaurant_pos.shared.coupon.services import (
	COUPON_STATUS_ACTIVE,
	COUPON_STATUS_EXPIRED,
	_discount_base,
	ensure_draft_sales_invoice,
	normalize_coupon_name,
	resolve_applied_coupon_code,
)
from excel_restaurant_pos.shared.gift_card.services import (
	is_gift_card_redemption_channel_allowed,
	recompute_available_balance,
)
from excel_restaurant_pos.shared.gift_card.validation import GIFT_CARD_TYPE

APPLIED_TABLE = "custom_applied_gift_cards"


def _applied_rows(doc) -> list:
	return list(doc.get(APPLIED_TABLE) or [])


def _row_gift_card_code(row) -> str:
	"""Resolve a row's gift card code; fall back to raw value if not in DB."""
	raw = (row.get("gift_card_code") if hasattr(row, "get") else getattr(row, "gift_card_code", None)) or ""
	raw = str(raw).strip()
	return normalize_coupon_name(raw) or raw


def sum_applied_gift_amounts(doc, exclude_code: str | None = None) -> float:
	"""Sum redeemed amounts already on the invoice."""
	exclude_raw = (exclude_code or "").strip()
	exclude = (normalize_coupon_name(exclude_raw) or exclude_raw) if exclude_raw else ""
	total = 0.0
	for row in _applied_rows(doc):
		code = _row_gift_card_code(row)
		if exclude and code == exclude:
			continue
		total += flt(row.get("redeemed_amount") if hasattr(row, "get") else getattr(row, "redeemed_amount", 0))
	return total


def remaining_gift_redeemable(doc, exclude_code: str | None = None) -> float:
	"""Invoice amount still available for gift card discount."""
	base = _discount_base(doc)
	already = sum_applied_gift_amounts(doc, exclude_code=exclude_code)
	remaining = flt(base) - already
	return remaining if remaining > 0 else 0.0


def invoice_has_applied_gift_cards(doc) -> bool:
	return bool(_applied_rows(doc))


def invoice_has_promo_coupon(doc) -> bool:
	"""True when a non–gift-card promo coupon is applied."""
	code = resolve_applied_coupon_code(doc)
	if not code:
		return False
	coupon_type = frappe.db.get_value("Coupon Code", code, "coupon_type")
	return (coupon_type or "").strip() != GIFT_CARD_TYPE


def assert_no_promo_coupon(doc):
	if invoice_has_promo_coupon(doc):
		frappe.throw(_("Cannot redeem gift cards together with a promotional coupon."))


def assert_no_gift_cards(doc):
	if invoice_has_applied_gift_cards(doc):
		frappe.throw(_("Cannot apply a promotional coupon while gift cards are applied."))


def _load_active_gift_card(coupon_code: str):
	coupon_name = normalize_coupon_name(coupon_code)
	if not coupon_name:
		frappe.throw(_("Gift Card {0} does not exist.").format(coupon_code), frappe.DoesNotExistError)

	coupon = frappe.get_doc("Coupon Code", coupon_name)
	if (coupon.coupon_type or "").strip() != GIFT_CARD_TYPE:
		frappe.throw(_("Coupon {0} is not a Gift Card. Use the promo coupon APIs.").format(coupon.name))

	status = (coupon.custom_status or "").strip()
	if status != COUPON_STATUS_ACTIVE:
		frappe.throw(_("Gift Card {0} is {1}.").format(coupon.name, status.lower() or _("invalid")))

	return coupon


def validate_gift_card_for_redemption(doc, coupon):
	"""Shared redemption rules for verify/apply/validate hooks."""
	if not is_gift_card_redemption_channel_allowed(doc):
		frappe.throw(_("Gift card redemption is not allowed for this order type."))

	assert_no_promo_coupon(doc)

	if coupon.custom_generated_on_order == doc.name:
		frappe.throw(_("Cannot redeem gift card {0} on the invoice that sold it.").format(coupon.name))

	posting_date = getdate(doc.get("posting_date") or nowdate())
	if coupon.valid_from and posting_date < getdate(coupon.valid_from):
		frappe.throw(_("Gift Card {0} is not yet valid.").format(coupon.name))

	if coupon.valid_upto and posting_date > getdate(coupon.valid_upto):
		coupon.custom_status = COUPON_STATUS_EXPIRED
		coupon.save(ignore_permissions=True)
		frappe.throw(_("Gift Card {0} has expired.").format(coupon.name))

	balance = flt(coupon.custom_available_balance)
	if balance <= 0:
		frappe.throw(_("Gift Card {0} has no available balance.").format(coupon.name))

	return balance


def preview_gift_card_redemption(doc, coupon) -> dict:
	"""Return how much this card would redeem given cards already applied."""
	balance = validate_gift_card_for_redemption(doc, coupon)
	remaining = remaining_gift_redeemable(doc, exclude_code=coupon.name)
	redeemed_amount = min(balance, remaining)
	return {
		"gift_card_code": coupon.name,
		"coupon_code": coupon.coupon_code,
		"available_balance": balance,
		"remaining_invoice_due": remaining,
		"redeemed_amount": flt(redeemed_amount),
		"valid_from": coupon.valid_from,
		"valid_upto": coupon.valid_upto,
		"custom_status": coupon.custom_status,
	}


def apply_gift_card_discount_to_doc(doc):
	"""Set invoice discount_amount from applied gift cards."""
	total = sum_applied_gift_amounts(doc)
	if total <= 0:
		# Only clear discount if we were owning a gift-card discount (no promo).
		if not resolve_applied_coupon_code(doc):
			# Leave manual discounts alone when no gift cards — only clear when
			# rows were just emptied and flag says we applied gift discount.
			if doc.flags.get("gift_card_discount_applied"):
				doc.discount_amount = 0
				doc.additional_discount_percentage = 0
				doc.flags.gift_card_discount_applied = False
		return

	doc.apply_discount_on = doc.apply_discount_on or "Net Total"
	doc.additional_discount_percentage = 0
	doc.discount_amount = flt(total)
	doc.flags.gift_card_discount_applied = True
	doc.calculate_taxes_and_totals()


def verify_gift_card_for_sales_invoice(docname: str, coupon_code: str) -> dict:
	"""Validate a gift card for an invoice without applying it."""
	doc = frappe.get_doc("Sales Invoice", docname)
	ensure_draft_sales_invoice(doc)

	coupon = _load_active_gift_card(coupon_code)
	preview = preview_gift_card_redemption(doc, coupon)

	already = {
		normalize_coupon_name(r.get("gift_card_code")) for r in _applied_rows(doc)
	}
	if coupon.name in already:
		frappe.throw(_("Gift Card {0} is already applied on this invoice.").format(coupon.name))

	return {
		"status": "success",
		"valid": True,
		"sales_invoice": doc.name,
		**preview,
		"already_applied_total": sum_applied_gift_amounts(doc),
	}


def apply_gift_card_to_sales_invoice(docname: str, coupon_code: str) -> dict:
	"""Apply one gift card (backward-compatible wrapper)."""
	return apply_gift_cards_to_sales_invoice(docname, [coupon_code])


def parse_gift_card_codes(*raw_values) -> list[str]:
	"""Normalize one or many gift card codes into an ordered unique list.

	Accepts:
	- a single string: ``"A"`` or ``"A,B,C"`` or newline-separated
	- a list/tuple of strings
	- nested mixes of the above
	"""
	codes: list[str] = []
	seen: set[str] = set()

	def _add(value):
		if value is None:
			return
		if isinstance(value, (list, tuple)):
			for item in value:
				_add(item)
			return
		text = str(value).strip()
		if not text:
			return
		# Split on comma / newline / semicolon (scanner or multi-entry UX)
		parts = []
		for chunk in text.replace(";", ",").replace("\n", ",").split(","):
			part = chunk.strip()
			if part:
				parts.append(part)
		for part in parts:
			key = part.upper()
			if key in seen:
				continue
			seen.add(key)
			codes.append(part)

	for raw in raw_values:
		_add(raw)
	return codes


def _append_one_gift_card(doc, coupon_code: str) -> dict:
	"""Append one gift card row onto ``doc`` (no save). Returns apply detail."""
	coupon = _load_active_gift_card(coupon_code)
	preview = preview_gift_card_redemption(doc, coupon)

	already = {
		normalize_coupon_name(r.get("gift_card_code")) for r in _applied_rows(doc)
	}
	if coupon.name in already:
		frappe.throw(_("Gift Card {0} is already applied on this invoice.").format(coupon.name))

	amount = flt(preview["redeemed_amount"])
	if amount <= 0:
		frappe.throw(
			_("Nothing left to redeem on this invoice with gift card {0}.").format(coupon.name)
		)

	doc.append(
		APPLIED_TABLE,
		{"gift_card_code": coupon.name, "redeemed_amount": amount},
	)
	return {
		"gift_card_code": coupon.name,
		"coupon_code": coupon.coupon_code,
		"redeemed_amount": amount,
		"available_balance": preview["available_balance"],
	}


def apply_gift_cards_to_sales_invoice(docname: str, coupon_codes) -> dict:
	"""Apply one or more gift cards in order (first → last) until due is covered.

	Later codes are skipped when the invoice is already fully covered.
	Invalid codes raise (same as single apply) so the cashier can fix input.
	"""
	codes = parse_gift_card_codes(coupon_codes)
	if not codes:
		frappe.throw(_("At least one gift card code is required."))

	doc = frappe.get_doc("Sales Invoice", docname)
	ensure_draft_sales_invoice(doc)
	assert_no_promo_coupon(doc)

	newly_applied: list[dict] = []
	skipped: list[dict] = []

	for code in codes:
		remaining = remaining_gift_redeemable(doc)
		if remaining <= 0:
			skipped.append(
				{
					"gift_card_code": code,
					"reason": _("Invoice already fully covered by previous gift cards."),
				}
			)
			continue
		detail = _append_one_gift_card(doc, code)
		newly_applied.append(detail)

	if not newly_applied:
		# All skipped because fully covered, or nothing applied
		if skipped:
			frappe.throw(_("Invoice is already fully covered; no gift cards were applied."))
		frappe.throw(_("No gift cards were applied."))

	apply_gift_card_discount_to_doc(doc)
	doc.save(ignore_permissions=True)

	return {
		"status": "success",
		"applied": True,
		"sales_invoice": doc.name,
		# Backward-compatible single-card fields (first newly applied)
		"gift_card_code": newly_applied[0]["gift_card_code"],
		"coupon_code": newly_applied[0].get("coupon_code"),
		"redeemed_amount": sum(flt(r["redeemed_amount"]) for r in newly_applied),
		"available_balance": newly_applied[0].get("available_balance"),
		"newly_applied": newly_applied,
		"skipped": skipped,
		"applied_gift_cards": [
			{
				"gift_card_code": normalize_coupon_name(r.gift_card_code),
				"redeemed_amount": flt(r.redeemed_amount),
			}
			for r in _applied_rows(doc)
		],
		"invoice_discount_amount": flt(doc.discount_amount),
		"grand_total": flt(doc.grand_total),
	}


def discard_gift_card_from_sales_invoice(docname: str, coupon_code: str | None = None) -> dict:
	"""Remove one applied gift card, or all if coupon_code is omitted."""
	doc = frappe.get_doc("Sales Invoice", docname)
	ensure_draft_sales_invoice(doc)

	rows = _applied_rows(doc)
	if not rows:
		return {
			"status": "success",
			"discarded": False,
			"sales_invoice": doc.name,
			"message": _("No gift cards were applied."),
		}

	target = normalize_coupon_name(coupon_code) if coupon_code else None
	kept = []
	removed = []
	for row in rows:
		code = normalize_coupon_name(row.get("gift_card_code"))
		if target is None or code == target:
			removed.append({"gift_card_code": code, "redeemed_amount": flt(row.get("redeemed_amount"))})
		else:
			kept.append(row)

	if target and not removed:
		frappe.throw(_("Gift Card {0} is not applied on this invoice.").format(target))

	doc.set(APPLIED_TABLE, [])
	for row in kept:
		doc.append(
			APPLIED_TABLE,
			{
				"gift_card_code": row.get("gift_card_code"),
				"redeemed_amount": flt(row.get("redeemed_amount")),
			},
		)

	doc.flags.gift_card_discount_applied = True
	apply_gift_card_discount_to_doc(doc)
	if not _applied_rows(doc):
		doc.discount_amount = 0
		doc.additional_discount_percentage = 0
		doc.calculate_taxes_and_totals()
		doc.flags.gift_card_discount_applied = False

	doc.save(ignore_permissions=True)

	return {
		"status": "success",
		"discarded": True,
		"sales_invoice": doc.name,
		"removed": removed,
		"applied_gift_cards": [
			{
				"gift_card_code": normalize_coupon_name(r.gift_card_code),
				"redeemed_amount": flt(r.redeemed_amount),
			}
			for r in _applied_rows(doc)
		],
		"invoice_discount_amount": flt(doc.discount_amount),
		"grand_total": flt(doc.grand_total),
	}


def apply_sales_invoice_gift_card_discount(doc, method=None):
	"""Validate hook: keep discount in sync with applied gift cards."""
	if not _applied_rows(doc):
		return

	assert_no_promo_coupon(doc)
	# Re-allocate amounts against current invoice total (items may have changed)
	reallocated = []
	remaining = flt(_discount_base(doc))
	seen = set()
	for row in _applied_rows(doc):
		code = normalize_coupon_name(row.get("gift_card_code"))
		if not code or code in seen:
			continue
		seen.add(code)
		coupon = _load_active_gift_card(code)
		balance = validate_gift_card_for_redemption(doc, coupon)
		amount = min(balance, remaining, flt(row.get("redeemed_amount")) or remaining)
		if amount <= 0:
			continue
		reallocated.append({"gift_card_code": code, "redeemed_amount": amount})
		remaining -= amount

	doc.set(APPLIED_TABLE, [])
	for row in reallocated:
		doc.append(APPLIED_TABLE, row)

	apply_gift_card_discount_to_doc(doc)


def validate_sales_invoice_gift_card_redemption(doc, method=None):
	"""Validate applied gift cards on draft/submit validate."""
	rows = _applied_rows(doc)
	if not rows:
		return

	assert_no_promo_coupon(doc)
	if not is_gift_card_redemption_channel_allowed(doc):
		frappe.throw(_("Gift card redemption is not allowed for this order type."))

	seen = set()
	for row in rows:
		code = normalize_coupon_name(row.get("gift_card_code"))
		amount = flt(row.get("redeemed_amount"))
		if not code or amount <= 0:
			frappe.throw(_("Each applied gift card must have a code and redeemed amount."))
		if code in seen:
			frappe.throw(_("Gift Card {0} is applied more than once.").format(code))
		seen.add(code)

		coupon = _load_active_gift_card(code)
		balance = validate_gift_card_for_redemption(doc, coupon)
		if amount > balance + 0.0001:
			frappe.throw(
				_("Gift Card {0} has insufficient balance ({1}).").format(
					code, frappe.format_value(balance, {"fieldtype": "Currency"})
				)
			)

	total = sum_applied_gift_amounts(doc)
	base = _discount_base(doc)
	if total > base + 0.0001:
		frappe.throw(_("Total gift card discount cannot exceed the invoice total."))


def list_inactive_gift_cards(search: str | None = None, limit: int = 20) -> list[dict]:
	"""Search Inactive gift cards for Existing-type picker (name/code or QR/barcode)."""
	limit = min(cint(limit) or 20, 100)
	filters = {
		"coupon_type": GIFT_CARD_TYPE,
		"custom_status": "Inactive",
	}
	or_filters = None
	if search:
		raw = search.strip()
		# Exact barcode / QR match first (scanner paste)
		exact = frappe.get_all(
			"Coupon Code",
			filters={
				**filters,
			},
			or_filters=[
				["coupon_code", "=", raw],
				["coupon_name", "=", raw],
				["name", "=", raw],
				["custom_barcode", "=", raw],
				["custom_qr_code", "=", raw],
			],
			fields=[
				"name",
				"coupon_code",
				"coupon_name",
				"custom_discount_amount",
				"custom_available_balance",
				"custom_status",
				"custom_linked_email",
				"custom_qr_code",
				"custom_barcode",
				"valid_from",
				"valid_upto",
			],
			limit_page_length=limit,
		)
		if exact:
			return exact

		term = f"%{raw}%"
		or_filters = [
			["coupon_code", "like", term],
			["coupon_name", "like", term],
			["name", "like", term],
			["custom_barcode", "like", term],
			["custom_qr_code", "like", term],
		]

	rows = frappe.get_all(
		"Coupon Code",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"coupon_code",
			"coupon_name",
			"custom_discount_amount",
			"custom_available_balance",
			"custom_status",
			"custom_linked_email",
			"custom_qr_code",
			"custom_barcode",
			"valid_from",
			"valid_upto",
		],
		order_by="modified desc",
		limit_page_length=limit,
	)
	return rows


def list_gift_cards(
	status: str | None = None,
	search: str | None = None,
	limit: int = 50,
	offset: int = 0,
) -> dict:
	"""Admin list of gift cards with optional status/search filters."""
	limit = min(cint(limit) or 50, 200)
	offset = max(cint(offset) or 0, 0)
	filters: dict = {"coupon_type": GIFT_CARD_TYPE}
	if status:
		filters["custom_status"] = status.strip()

	or_filters = None
	if search:
		term = f"%{search.strip()}%"
		or_filters = [
			["coupon_code", "like", term],
			["coupon_name", "like", term],
			["name", "like", term],
			["custom_linked_email", "like", term],
		]

	rows = frappe.get_all(
		"Coupon Code",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"coupon_code",
			"custom_status",
			"custom_discount_amount",
			"custom_available_balance",
			"custom_linked_email",
			"custom_generated_on_order",
			"valid_from",
			"valid_upto",
			"custom_created_on",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=limit,
		limit_start=offset,
	)
	total = frappe.db.count("Coupon Code", filters=filters)
	return {"status": "success", "data": rows, "total": total, "limit": limit, "offset": offset}
