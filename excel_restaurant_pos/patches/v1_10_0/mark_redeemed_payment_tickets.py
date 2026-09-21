"""Mark every Payment Ticket that has already paid for its order as redeemed.

The claim in api/payments/helper/claim_ticket.py only protects tickets from the
moment it is deployed. Every ticket paid before then still has an empty
redeemed_at, and Moneris answers "approved" for them forever -- so without this,
the tickets most worth replaying are exactly the ones left open.

A ticket counts as spent when its invoice is submitted or cancelled. Tickets on
draft invoices are left alone: those orders may still be paid legitimately.
Tickets whose invoice no longer exists are left alone too -- receipt_payment
fails on the missing invoice before it could pay for anything.
"""

import frappe


def execute():
	if not frappe.db.has_column("Payment Ticket", "redeemed_at"):
		return

	frappe.db.sql(
		"""
		update `tabPayment Ticket` pt
		join `tabSales Invoice` si on si.name = pt.invoice_no
		set pt.redeemed_at = now(), pt.redeemed_via = 'backfill'
		where pt.redeemed_at is null and si.docstatus in (1, 2)
		"""
	)
