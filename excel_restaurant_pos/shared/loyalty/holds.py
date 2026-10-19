"""Points held by an online checkout while the card is being charged.

A website order applies points to its draft, gets a gateway ticket, and is only
submitted -- which is when the points are spent -- after the card is charged.
Without a hold, points spent elsewhere in between (the POS, a reward, a second
tab) left the order with a charged card and an invoice that refused to submit.

A draft with a Payment Ticket now holds its points: every other spend sees the
balance less what such drafts hold. The hold lasts as long as the ticket does --
changing the points deletes the ticket, and the stale-order sweep deletes or
settles the draft. A paid order submits even if the points are gone (expired or
taken by a manual adjustment while it waited): the member then owes the
shortfall, which their next earnings settle.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from excel_restaurant_pos.shared.loyalty import ledger
from excel_restaurant_pos.shared.payment_ticket import IN_CHECKOUT_SQL, paid_by_card, tickets_exist  # noqa: F401

INVOICE = "Sales Invoice"
POINTS_FIELD = "custom_loyalty_points_redeemed"
ACCOUNT_FIELD = "custom_loyalty_account"


def held_points(account: str, exclude_invoice: str | None = None, for_update: bool = False) -> int:
	"""Points that drafts with a payment ticket hold, other than `exclude_invoice`'s."""
	if not account or not tickets_exist():
		return 0
	row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(si.{POINTS_FIELD}), 0)
		FROM `tab{INVOICE}` si
		WHERE si.{ACCOUNT_FIELD} = %(account)s
			AND si.docstatus = 0
			AND si.{POINTS_FIELD} > 0
			AND si.name != %(exclude)s
			AND {IN_CHECKOUT_SQL}
		{"LOCK IN SHARE MODE" if for_update else ""}
		""",
		{"account": account, "exclude": exclude_invoice or ""},
	)
	return cint(row[0][0]) if row else 0


def spendable(account: str, exclude_invoice: str | None = None, for_update: bool = False) -> int:
	"""The balance less what other orders' checkouts hold.

	`for_update` is for callers holding the account lock: it reads the latest
	committed rows rather than the transaction's REPEATABLE-READ snapshot."""
	return ledger.available_balance(account, for_update=for_update) - held_points(
		account, exclude_invoice, for_update=for_update
	)


def assert_spendable(account: str, points: int, exclude_invoice: str | None = None):
	"""Under the account lock: refuse a spend that would eat into a hold."""
	free = spendable(account, exclude_invoice, for_update=True)
	if cint(points) > free:
		frappe.throw(
			_("Not enough loyalty points: {0} requested, {1} available.").format(cint(points), max(free, 0)),
			title=_("Loyalty Points"),
		)


def hold_for_checkout(invoice):
	"""Before a payment ticket is saved: the order's points must still be free.

	Called under the transaction that saves the ticket, so once the ticket is
	committed the hold is visible to every other spend."""
	points = cint(invoice.get(POINTS_FIELD))
	account = invoice.get(ACCOUNT_FIELD)
	if points <= 0 or not account:
		return
	ledger.lock_account(account)
	free = spendable(account, exclude_invoice=invoice.name, for_update=True)
	if points > free:
		frappe.throw(
			_(
				"Only {0} loyalty points are available now, but this order uses {1}. "
				"Change the points on the order and pay again."
			).format(max(free, 0), points),
			title=_("Loyalty Points"),
		)
