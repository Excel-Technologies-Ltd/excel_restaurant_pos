"""Settle an order that a gift card (or coupon) has already paid in full.

A Website order is Pay First: the only route to `docstatus = 1` runs through the
payment gateway. When a gift card covers the whole basket the gateway is asked
to open a $0 transaction, refuses, and the order is stranded as a draft — so the
`on_submit` hook that actually spends the gift card never runs and the customer's
balance is never touched.

Nothing has to be collected for such an order, so the gateway is skipped and the
invoice is submitted here instead. It reaches Paid on its own (outstanding is
already zero), which is what drives the normal order-status flow.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt


def _discard_payment_tickets(invoice_name: str) -> None:
	"""Remove payment tickets for an invoice that no longer needs paying."""
	for name in frappe.get_all(
		"Payment Ticket", filters={"invoice_no": invoice_name}, pluck="name"
	):
		frappe.delete_doc("Payment Ticket", name, ignore_permissions=True, force=True)


def is_fully_discounted(invoice) -> bool:
	"""True when there is nothing left to charge for this invoice."""
	return flt(invoice.grand_total) <= 0


def settle_zero_payment(invoice) -> dict:
	"""Submit a fully discounted invoice without touching the payment gateway.

	Returns the same shape whether it submits now or finds the invoice already
	submitted: the storefront may retry, and a double tap must not be an error.
	"""
	if cint(invoice.docstatus) == 2:
		frappe.throw(_("Order {0} was cancelled.").format(invoice.name), frappe.ValidationError)

	if cint(invoice.docstatus) == 0:
		# Guard the free-order case: only a coupon or gift card may take an
		# invoice to zero. Anything else reaching zero (zero-priced items, a
		# hand-edited discount) is refused rather than quietly submitted, which
		# matters because this endpoint is guest reachable. `validate` enforces
		# the same rule, so an invoice failing it should not exist at all.
		# Imported here, not at module scope: excel_restaurant_pos.api imports
		# this module, and doc_event.sales_invoice imports back into
		# excel_restaurant_pos.api.item_group. At module scope that cycle only
		# resolves because of the order the route modules happen to be listed in.
		from excel_restaurant_pos.doc_event.sales_invoice.validate_zero_value import (
			zero_total_is_discount_backed,
		)

		if not zero_total_is_discount_backed(invoice):
			frappe.throw(
				_(
					"Order {0} has no amount to pay and no coupon or gift card that "
					"explains it."
				).format(invoice.name),
				frappe.ValidationError,
			)

		# Drop any ticket minted while the order still had a balance. Left
		# behind it stays replayable through api.payments.receipt_payment,
		# which would try to submit this invoice a second time.
		_discard_payment_tickets(invoice.name)

		invoice.flags.ignore_permissions = True
		invoice.submit()

	return {
		# The storefront branches on this: there is no ticket to redirect to.
		"payment_required": False,
		"paid": True,
		"invoice": invoice.name,
		"grand_total": flt(invoice.grand_total),
		"status": invoice.get("status"),
	}
