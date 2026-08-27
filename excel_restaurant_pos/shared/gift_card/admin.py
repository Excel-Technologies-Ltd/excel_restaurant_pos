"""Admin operations: bulk create and CSV import of Inactive gift cards."""

from __future__ import annotations

import csv
import io
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from excel_restaurant_pos.shared.coupon.services import generate_unique_coupon_code
from excel_restaurant_pos.shared.gift_card.services import (
	_validate_gift_pricing_rule,
	get_gift_card_settings,
)
from excel_restaurant_pos.shared.gift_card.validation import GIFT_CARD_TYPE, STATUS_INACTIVE

MAX_BULK_QTY = 500
MAX_IMPORT_ROWS = 2000


def _create_inactive_gift_card(
	*,
	amount: float,
	pricing_rule: str,
	prefix: str,
	linked_email: str | None = None,
	coupon_code: str | None = None,
) -> str:
	"""Insert one Inactive Gift Card Coupon Code; return its name."""
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Gift Card amount must be greater than zero."))

	code = (coupon_code or "").strip().upper()
	if code:
		if frappe.db.exists("Coupon Code", code) or frappe.db.exists(
			"Coupon Code", {"coupon_code": code}
		):
			frappe.throw(_("Gift Card code {0} already exists.").format(code))
	else:
		code = generate_unique_coupon_code(prefix)

	doc = frappe.get_doc(
		{
			"doctype": "Coupon Code",
			"name": code,
			"coupon_name": code,
			"coupon_code": code,
			"coupon_type": GIFT_CARD_TYPE,
			"pricing_rule": pricing_rule,
			"maximum_use": 0,
			"used": 0,
			"custom_discount_type": "Flat Amount",
			"custom_discount_amount": amount,
			"custom_available_balance": amount,
			"custom_created_on": now_datetime(),
			"custom_linked_email": (linked_email or "").strip() or None,
			"custom_status": STATUS_INACTIVE,
			"custom_order_status": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def generate_bulk_inactive_gift_cards(
	qty: int,
	amount: float,
	*,
	prefix: str | None = None,
	linked_email: str | None = None,
) -> dict[str, Any]:
	"""Create N Inactive gift cards with the same face value."""
	qty = cint(qty)
	if qty < 1:
		frappe.throw(_("Quantity must be at least 1."))
	if qty > MAX_BULK_QTY:
		frappe.throw(_("Quantity cannot exceed {0}.").format(MAX_BULK_QTY))

	settings = get_gift_card_settings()
	pricing_rule = _validate_gift_pricing_rule(settings)
	code_prefix = (prefix or getattr(settings, "gift_card_prefix", None) or "GIFT####").strip()

	created: list[str] = []
	for _ in range(qty):
		created.append(
			_create_inactive_gift_card(
				amount=amount,
				pricing_rule=pricing_rule,
				prefix=code_prefix,
				linked_email=linked_email,
			)
		)

	return {
		"status": "success",
		"created_count": len(created),
		"codes": created,
		"amount": flt(amount),
	}


def _parse_import_rows(raw_text: str) -> list[dict]:
	"""Parse CSV text into row dicts. Supports headers or plain columns."""
	text = (raw_text or "").strip()
	if not text:
		frappe.throw(_("Import data is empty."))

	# Strip BOM
	if text.startswith("\ufeff"):
		text = text[1:]

	reader = csv.reader(io.StringIO(text))
	rows = list(reader)
	if not rows:
		frappe.throw(_("Import data is empty."))

	header = [c.strip().lower() for c in rows[0]]
	has_header = any(
		h in ("code", "coupon_code", "amount", "face_value", "email", "linked_email")
		for h in header
	)

	parsed: list[dict] = []
	if has_header:
		col = {name: idx for idx, name in enumerate(header)}

		def _cell(row, *names):
			for n in names:
				if n in col and col[n] < len(row):
					return (row[col[n]] or "").strip()
			return ""

		for row in rows[1:]:
			if not any((c or "").strip() for c in row):
				continue
			parsed.append(
				{
					"code": _cell(row, "code", "coupon_code", "name"),
					"amount": _cell(row, "amount", "face_value", "value"),
					"email": _cell(row, "email", "linked_email"),
				}
			)
	else:
		# Columns: amount[, code][, email]  OR  code, amount[, email]
		for row in rows:
			cells = [(c or "").strip() for c in row]
			if not any(cells):
				continue
			if len(cells) == 1:
				parsed.append({"code": "", "amount": cells[0], "email": ""})
			elif len(cells) >= 2:
				# If first looks numeric → amount, code optional second
				first = cells[0].replace(",", "")
				if first.replace(".", "", 1).isdigit():
					parsed.append(
						{
							"code": cells[1] if len(cells) > 1 and not cells[1].replace(".", "", 1).isdigit() else "",
							"amount": cells[0],
							"email": cells[2] if len(cells) > 2 else (cells[1] if "@" in (cells[1] or "") else ""),
						}
					)
				else:
					parsed.append(
						{
							"code": cells[0],
							"amount": cells[1],
							"email": cells[2] if len(cells) > 2 else "",
						}
					)

	if len(parsed) > MAX_IMPORT_ROWS:
		frappe.throw(_("Import cannot exceed {0} rows.").format(MAX_IMPORT_ROWS))
	if not parsed:
		frappe.throw(_("No data rows found in import."))

	return parsed


def import_inactive_gift_cards(csv_text: str) -> dict[str, Any]:
	"""Import Inactive gift cards from CSV text.

	Supported headers: code/coupon_code, amount/face_value, email/linked_email
	Code is optional — auto-generated from ArcPOS Settings prefix when blank.
	"""
	settings = get_gift_card_settings()
	pricing_rule = _validate_gift_pricing_rule(settings)
	prefix = (getattr(settings, "gift_card_prefix", None) or "GIFT####").strip()

	rows = _parse_import_rows(csv_text)
	created: list[str] = []
	errors: list[dict] = []

	for idx, row in enumerate(rows, start=1):
		try:
			amount = flt(row.get("amount"))
			if amount <= 0:
				frappe.throw(_("Row {0}: amount is required.").format(idx))
			name = _create_inactive_gift_card(
				amount=amount,
				pricing_rule=pricing_rule,
				prefix=prefix,
				linked_email=row.get("email"),
				coupon_code=row.get("code") or None,
			)
			created.append(name)
		except Exception as exc:
			errors.append({"row": idx, "message": str(exc)})

	return {
		"status": "success" if created and not errors else ("partial" if created else "error"),
		"created_count": len(created),
		"codes": created,
		"error_count": len(errors),
		"errors": errors[:50],
	}
