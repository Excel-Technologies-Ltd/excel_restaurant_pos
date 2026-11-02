"""Gift card amounts held by an online checkout while the card is being charged.

A website order applies gift cards to its draft, gets a gateway ticket for the
rest, and only spends the gift cards when it submits -- after the bank card is
charged. A gift card spent elsewhere in between used to leave a charged order
that refused to submit (or, worse, re-shrank its gift card discount so the
order owed more than was charged).

A draft with a Payment Ticket now holds the amounts it applied: every other
order sees each card's balance less what such drafts hold, and the ticket is
refused up front when the balance is no longer there. An order whose ticket was
claimed as paid keeps the amounts it was charged against, and submits even if
a card was drained some other way meanwhile; the overdraw is logged for staff.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from excel_restaurant_pos.shared.payment_ticket import IN_CHECKOUT_SQL, tickets_exist

APPLIED_DOCTYPE = "Applied Gift Cards"
APPLIED_FIELD = "custom_applied_gift_cards"
REDEEMED_DOCTYPE = "Coupon Redeemed on Orders"
REDEEMED_FIELD = "custom_coupon_redeemed_on_orders"
TOLERANCE = 0.0001


def held_amount(coupon: str, exclude_invoice: str | None = None, for_update: bool = False) -> float:
	"""What drafts in card checkout have applied from `coupon`, other than `exclude_invoice`."""
	if not coupon or not tickets_exist():
		return 0.0
	row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(agc.redeemed_amount), 0)
		FROM `tab{APPLIED_DOCTYPE}` agc
		JOIN `tabSales Invoice` si ON si.name = agc.parent
		WHERE agc.parenttype = 'Sales Invoice'
			AND agc.parentfield = %(field)s
			AND agc.gift_card_code = %(coupon)s
			AND si.docstatus = 0
			AND si.name != %(exclude)s
			AND {IN_CHECKOUT_SQL}
		{"LOCK IN SHARE MODE" if for_update else ""}
		""",
		{"field": APPLIED_FIELD, "coupon": coupon, "exclude": exclude_invoice or ""},
	)
	return flt(row[0][0]) if row else 0.0


def lock_card(coupon: str) -> frappe._dict:
	"""Row-lock a gift card for the rest of the transaction and read its live balance.

	Everything here is a locking read: the database is REPEATABLE-READ, so a
	plain read (or frappe.get_doc) can return the snapshot from before the lock
	was granted and miss a redemption another order just committed."""
	rows = frappe.db.sql(
		"""
		SELECT name, coupon_type, custom_status, valid_upto, custom_generated_on_order, custom_discount_amount
		FROM `tabCoupon Code`
		WHERE name = %s
		FOR UPDATE
		""",
		(coupon,),
		as_dict=True,
	)
	if not rows:
		frappe.throw(_("Gift Card {0} not found.").format(coupon), frappe.DoesNotExistError)
	card = rows[0]
	redemptions = frappe.db.sql(
		f"""
		SELECT sales_invoice, redeemed_amount, idx
		FROM `tab{REDEEMED_DOCTYPE}`
		WHERE parent = %s AND parenttype = 'Coupon Code' AND parentfield = %s
		LOCK IN SHARE MODE
		""",
		(coupon, REDEEMED_FIELD),
		as_dict=True,
	)
	card.redemptions = redemptions
	card.balance = max(flt(card.custom_discount_amount) - sum(flt(r.redeemed_amount) for r in redemptions), 0.0)
	return card


def hold_for_checkout(invoice):
	"""Before a payment ticket is saved: the order's gift card amounts must still be free.

	Called in the transaction that saves the ticket, so once it commits the hold
	is visible to every other order."""
	# In code order, so two orders sharing cards lock them in the same order.
	for row in sorted(invoice.get(APPLIED_FIELD) or [], key=lambda r: r.get("gift_card_code") or ""):
		code, amount = row.get("gift_card_code"), flt(row.get("redeemed_amount"))
		if not code or amount <= 0:
			continue
		card = lock_card(code)
		free = card.balance - held_amount(code, exclude_invoice=invoice.name, for_update=True)
		if amount > free + TOLERANCE:
			frappe.throw(
				_(
					"Gift Card {0} has only {1} available now, but this order uses {2}. "
					"Update the gift cards on the order and pay again."
				).format(
					code,
					frappe.format_value(max(free, 0), {"fieldtype": "Currency"}),
					frappe.format_value(amount, {"fieldtype": "Currency"}),
				),
				title=_("Gift Card"),
			)
