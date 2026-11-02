"""Gift cards on cancelled and returned orders.

A card's balance is its face value less its `Coupon Redeemed on Orders` rows.
A cancelled order's rows are removed, so what it spent comes back. A credit
note adds a negative row of its own: the card gets back what the credit note
does not refund in money. A gift card sold on an order and returned unused is
rejected, as a cancelled sale's card already is.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from excel_restaurant_pos.shared.coupon.order_status import (
	ORDER_STATUS_CANCELLED,
	apply_coupon_order_status,
	get_coupons_generated_on,
)
from excel_restaurant_pos.shared.coupon.services import COUPON_STATUS_ACTIVE, COUPON_STATUS_USED
from excel_restaurant_pos.shared.gift_card.holds import REDEEMED_DOCTYPE, REDEEMED_FIELD, lock_card
from excel_restaurant_pos.shared.gift_card.validation import GIFT_CARD_TYPE_EXISTING, get_gift_card_lines

INVOICE = "Sales Invoice"


def _rows_for(invoice: str) -> list[frappe._dict]:
	return frappe.get_all(
		REDEEMED_DOCTYPE,
		filters={"parenttype": "Coupon Code", "parentfield": REDEEMED_FIELD, "sales_invoice": invoice},
		fields=["name", "parent", "redeemed_amount", "idx"],
	)


def _refresh(code: str):
	"""Rewrite the card's balance and Used/Active status from its rows."""
	card = lock_card(code)
	values = {"custom_available_balance": card.balance}
	if (card.custom_status or "").strip() in (COUPON_STATUS_ACTIVE, COUPON_STATUS_USED):
		values["custom_status"] = COUPON_STATUS_USED if card.balance <= 0 else COUPON_STATUS_ACTIVE
	frappe.db.set_value("Coupon Code", code, values)


def on_invoice_cancel(doc, method=None):
	"""Sales Invoice on_cancel: give back what the order (or credit note) moved on each card."""
	rows = _rows_for(doc.name)
	# In code order, so two orders sharing cards lock them in the same order.
	for code in sorted({row.parent for row in rows}):
		lock_card(code)
		frappe.db.delete(REDEEMED_DOCTYPE, {"parent": code, "parentfield": REDEEMED_FIELD, "sales_invoice": doc.name})
		_refresh(code)


def on_return_submit(doc, method=None):
	"""Sales Invoice on_submit of a credit note: cards spent on the order, and cards it sold."""
	if not cint(doc.get("is_return")) or not doc.get("return_against"):
		return
	_restore_spent(doc)
	_reject_returned_sales(doc)


def _restore_spent(doc):
	"""Give back to the cards the part of the credit note that is not refunded in money.

	The gift cards were the order's discount, and a credit note carries that
	discount over (negated): the refund is the returned goods less it. The cards
	get back that discount, never more than the order spent from them and has
	not already had back from an earlier credit note.
	"""
	spent = _rows_for(doc.return_against)
	credit = abs(flt(doc.get("discount_amount")))
	if not spent or credit <= 0:
		return

	earlier = frappe.get_all(
		INVOICE,
		filters={"return_against": doc.return_against, "docstatus": 1, "name": ["!=", doc.name]},
		pluck="name",
	)
	per_card: dict[str, float] = {}
	for row in spent:
		per_card[row.parent] = per_card.get(row.parent, 0.0) + flt(row.redeemed_amount)
	for name in earlier:
		for row in _rows_for(name):
			if row.parent in per_card:
				per_card[row.parent] += flt(row.redeemed_amount)  # negative: already given back

	left = {code: amount for code, amount in per_card.items() if amount > 0}
	total_left = sum(left.values())
	if total_left <= 0:
		return
	give_back = min(credit, total_left)

	codes = sorted(left)
	given = 0.0
	for index, code in enumerate(codes):
		# Pro rata to what each card still has out; the last takes the rounding.
		share = give_back - given if index == len(codes) - 1 else flt(give_back * left[code] / total_left, 2)
		share = min(share, left[code])
		given += share
		if share <= 0:
			continue
		card = lock_card(code)
		if any(r.sales_invoice == doc.name for r in card.redemptions):
			continue
		frappe.get_doc(
			{
				"doctype": REDEEMED_DOCTYPE,
				"parent": code,
				"parenttype": "Coupon Code",
				"parentfield": REDEEMED_FIELD,
				"idx": max((cint(r.idx) for r in card.redemptions), default=0) + 1,
				"sales_invoice": doc.name,
				"redeemed_amount": -flt(share, 2),
			}
		).db_insert()
		_refresh(code)


def _reject_returned_sales(doc):
	"""Reject the unused gift cards whose sale this credit note refunds.

	A card someone has already spent from cannot be taken back here: it is
	logged for staff, since the refund paid out its face value.
	"""
	lines = get_gift_card_lines(doc)
	if not lines:
		return
	sold = get_coupons_generated_on(doc.return_against)
	if not sold:
		return

	taken: set[str] = set()
	for line in lines:
		count = abs(cint(line.get("qty"))) or 1
		if (line.get("custom_gift_card_type") or "").strip() == GIFT_CARD_TYPE_EXISTING:
			wanted = [line.get("custom_gift_card_code")] if line.get("custom_gift_card_code") in sold else []
		else:
			face = abs(flt(line.get("custom_gift_amount")))
			wanted = [
				code
				for code in sold
				if not face or abs(flt(frappe.db.get_value("Coupon Code", code, "custom_discount_amount")) - face) < 0.005
			]
		for code in wanted:
			if count <= 0:
				break
			if code in taken or not code:
				continue
			card = lock_card(code)
			if (card.custom_status or "").strip() == "Rejected":
				continue
			taken.add(code)
			count -= 1
			if card.redemptions:
				frappe.log_error(
					title="Returned gift card already spent",
					message=f"Credit note {doc.name} refunds gift card {code}, sold on {doc.return_against}, "
					f"but {flt(card.custom_discount_amount) - card.balance} of it has been spent. "
					"The card stays usable for its remaining balance; review the refund.",
				)
				continue
			apply_coupon_order_status(code, ORDER_STATUS_CANCELLED, reject=True)
