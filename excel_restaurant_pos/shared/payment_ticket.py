"""What a website order's gateway ticket says about the order.

A draft with a Payment Ticket is in card checkout: whatever it pays with
besides the card (loyalty points, gift cards) is held for it. Once the ticket
is claimed as paid, the card has been charged and the order must submit.
"""

from __future__ import annotations

import frappe

TICKET = "Payment Ticket"


def tickets_exist() -> bool:
	return bool(frappe.db.table_exists(TICKET))


# For SQL over Sales Invoice aliased `si`: the order is in card checkout.
IN_CHECKOUT_SQL = f"EXISTS (SELECT 1 FROM `tab{TICKET}` pt WHERE pt.invoice_no = si.name)"


def discard_tickets(invoice: str):
	"""After the order's points or gift cards change: a ticket preloaded at the
	old amount would be refused as a mismatch, and its hold is now wrong."""
	if not tickets_exist():
		return
	for name in frappe.get_all(TICKET, filters={"invoice_no": invoice}, pluck="name"):
		frappe.delete_doc(TICKET, name, ignore_permissions=True, force=True)


def paid_by_card(invoice: str | None) -> bool:
	"""Whether the order's gateway ticket was claimed as paid (in this transaction or before)."""
	if not invoice or not tickets_exist() or not frappe.get_meta(TICKET).has_field("redeemed_at"):
		return False
	return bool(
		frappe.db.sql(
			f"SELECT 1 FROM `tab{TICKET}` WHERE invoice_no = %s AND redeemed_at IS NOT NULL LIMIT 1",
			(invoice,),
		)
	)
