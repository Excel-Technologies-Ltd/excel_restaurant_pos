"""What a settled Moneris payment is worth, decided by the server.

receipt_payment used to take the amount for the Payment Entry from the request
body -- `payments[].amount`, whatever the browser sent -- and check only that
Moneris called the ticket paid, never how much it was paid for. So a $5 payment
could be booked as a $500 one. Worse, because a draft invoice can still be
edited after its ticket is issued, the cart could be grown after preloading at
$1: pay the $1 ticket, and the order went to the kitchen at full size, booked as
fully paid.

Both paths that settle tickets -- api.payments.receipt_payment and the stale
website order sweep -- now use the invoice's own grand_total for the Payment
Entry, and first check it against what Moneris says it charged.
"""

import frappe
from frappe.utils import flt

# convert_to_flt_string formats the preload total to cents, so a sub-cent
# difference is formatting, not fraud.
AMOUNT_TOLERANCE = 0.01

MATCH, MISMATCH, UNKNOWN = "match", "mismatch", "unknown"


def charged_amount(receipt_status):
	"""What Moneris says was charged, or None if the receipt does not say.

	`receipt.cc.amount` is what the card was actually charged; `request.txn_total`
	is what the ticket was preloaded for, which this server set from the invoice
	at preload time. The first one present wins.
	"""
	receipt = receipt_status.get("receipt") or {}
	request = receipt_status.get("request") or {}

	for value in ((receipt.get("cc") or {}).get("amount"), request.get("txn_total")):
		if value not in (None, ""):
			try:
				return flt(value, 2)
			except (TypeError, ValueError):
				continue

	return None


def verify_charged_amount(receipt_status, invoice):
	"""MATCH, MISMATCH, or UNKNOWN when the receipt carries no amount.

	UNKNOWN is logged and let through, not refused. The shape of a paid receipt
	was not observable from the sandbox without a live card payment, and
	refusing on our own parsing uncertainty would fail every real payment --
	customers charged, orders refused. The first logged UNKNOWN in production
	will show whether the fields above are the right ones.
	"""
	charged = charged_amount(receipt_status)
	expected = flt(invoice.grand_total, 2)

	if charged is None:
		frappe.log_error(
			title="Payment amount could not be verified",
			message=(
				f"invoice={invoice.name} grand_total={expected}\n"
				"The Moneris receipt carried neither receipt.cc.amount nor "
				"request.txn_total. Settled anyway; check the receipt shape.\n"
				f"receipt keys: {sorted((receipt_status.get('receipt') or {}).keys())}"
			),
		)
		return UNKNOWN

	if abs(charged - expected) > AMOUNT_TOLERANCE:
		frappe.log_error(
			title="Payment amount mismatch -- possible fraud",
			message=(
				f"invoice={invoice.name} grand_total={expected} "
				f"moneris_charged={charged}\n"
				"Not settled. If the invoice grew after its ticket was issued, "
				"the customer paid only for the smaller cart. Review and refund."
			),
		)
		return MISMATCH

	return MATCH


def website_mode_of_payment():
	"""The Mode of Payment configured for website orders, or None."""
	names = frappe.get_all(
		"Mode of Payment", filters={"custom_default_website": 1}, limit=1, pluck="name"
	)
	return names[0] if names else None


def settlement_payments(invoice, fallback_mode=None):
	"""The single payment row a settled ticket is booked as.

	The amount is always the invoice's grand_total. The mode is the configured
	website mode, so the request cannot pick which account the money lands in;
	`fallback_mode` is used only when no website mode is configured.
	"""
	mode = website_mode_of_payment()
	if not mode:
		frappe.log_error(
			title="No Mode Of payment",
			message="No mode of payment configured for website",
		)
		mode = fallback_mode or "Cash"

	return [{"mode_of_payment": mode, "amount": flt(invoice.grand_total, 2)}]
