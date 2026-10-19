"""Reversal: a cancelled invoice undoes its loyalty entries; a credit note undoes them pro rata."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from excel_restaurant_pos.shared.loyalty import campaigns, ledger, tiers
from excel_restaurant_pos.shared.loyalty.redemption import loyalty_mode, loyalty_payment_entries
from excel_restaurant_pos.shared.loyalty.rules import round_points
from excel_restaurant_pos.shared.loyalty.settings import TXN, get_programme

INVOICE = "Sales Invoice"


def _rows_for(invoice: str) -> list[frappe._dict]:
	return frappe.get_all(
		TXN,
		filters={"source_doctype": INVOICE, "source_name": invoice},
		fields=["name", "account", "programme", "transaction_type", "points", "campaign", "basis_items", "basis_qty"],
		order_by="creation asc",
	)


def undo_entry(row, key: str, programme, source_name: str, points: int | None = None) -> tuple[list[str], int]:
	"""Undo one ledger entry (or `points` of it). Returns (new entries, points not recovered)."""
	allow_negative = cint(programme.allow_negative_balance_on_reversal) if programme else 0
	grace = cint(programme.restore_grace_days) if programme else 7
	fields = {"source_doctype": INVOICE, "source_name": source_name, "campaign": row.campaign}
	if cint(row.points) > 0:
		name, shortfall = ledger.reverse_credit(row.account, row.name, key, points=points, allow_negative=allow_negative, **fields)
		return ([name] if name else []), shortfall
	return ledger.restore_debit(row.account, row.name, key, points=points, grace_days=grace, **fields), 0


def _finish(accounts: set, touched_campaigns: set):
	for account in accounts:
		ledger.recompute_cache(account, touch_activity=True)
	for campaign in touched_campaigns:
		campaigns.update_stats(campaign)


def on_invoice_cancel(doc, method=None):
	"""Sales Invoice on_cancel: reverse every loyalty entry the invoice produced.

	Runs whether or not loyalty is still switched on: entries that exist must
	be undone or the ledger and the books disagree. Earned points come back
	off the member; redeemed points are restored with their original expiry.
	"""
	_cancel_loyalty_payments(doc.name)
	_reverse_cancelled(doc)
	# After the reversal: an order that earned nothing still counted as spend.
	ledger.safely("Loyalty tier update failed", tiers.on_spend_reversed, doc, _("Order {0} cancelled").format(doc.name))


def _reverse_cancelled(doc):
	rows = _rows_for(doc.name)
	if not rows:
		return

	programme = get_programme(rows[0].programme)
	accounts, touched = set(), set()
	for row in rows:
		ledger.lock_account(row.account)
		undo_entry(row, f"reverse:{row.name}:cancel:{doc.name}", programme, doc.name)
		accounts.add(row.account)
		if row.campaign:
			touched.add(row.campaign)
	_finish(accounts, touched)


def _cancel_loyalty_payments(invoice: str):
	"""Cancel the Payment Entries that booked points tender against `invoice`.

	on_cancel runs before Frappe's back-link check, so cancelling them here
	keeps a submitted loyalty payment from blocking its own invoice.
	"""
	for name in loyalty_payment_entries(invoice):
		pe = frappe.get_doc("Payment Entry", name)
		pe.flags.ignore_permissions = True
		pe.cancel()


# ---------------------------------------------------------------- credit notes


def line_totals(doc) -> dict[str, dict]:
	totals: dict[str, dict] = {}
	for item in doc.get("items") or []:
		entry = totals.setdefault(item.get("item_code"), {"amount": 0.0, "qty": 0.0})
		entry["amount"] += abs(flt(item.get("base_net_amount") or item.get("net_amount") or item.get("amount")))
		entry["qty"] += abs(flt(item.get("qty")))
	return totals


def return_ratio(row, original_lines: dict, returned_lines: dict, original_net: float, returned_net: float) -> float:
	"""Share of one award a return takes back. Item rules look only at the returned matching lines."""
	items = json.loads(row.get("basis_items")) if row.get("basis_items") else None
	if items:
		key = "qty" if flt(row.get("basis_qty")) else "amount"
		original = sum(original_lines.get(code, {}).get(key, 0) for code in items)
		returned = sum(returned_lines.get(code, {}).get(key, 0) for code in items)
	else:
		original, returned = abs(flt(original_net)), abs(flt(returned_net))
	if original <= 0:
		return 0.0
	return min(returned / original, 1.0)


def on_return_submit(doc, method=None):
	"""Sales Invoice on_submit of a credit note: reverse earned points and restore redeemed ones pro rata."""
	if not cint(doc.get("is_return")) or not doc.get("return_against"):
		return
	_reverse_returned(doc)
	ledger.safely("Loyalty tier update failed", tiers.on_spend_reversed, doc, _("Return {0}").format(doc.name))


def _reverse_returned(doc):
	rows = _rows_for(doc.return_against)
	if not rows:
		return

	original = frappe.get_doc(INVOICE, doc.return_against)
	programme = get_programme(rows[0].programme)
	original_lines, returned_lines = line_totals(original), line_totals(doc)
	original_net = flt(original.base_net_total or original.net_total)
	returned_net = flt(doc.base_net_total or doc.net_total)
	total_ratio = min(abs(flt(doc.grand_total)) / flt(original.grand_total), 1.0) if flt(original.grand_total) else 0

	accounts, touched, restored_points = set(), set(), 0
	for row in rows:
		if row.transaction_type in ("Earn", "Bonus") and cint(row.points) > 0:
			ratio = return_ratio(row, original_lines, returned_lines, original_net, returned_net)
			points = round_points(cint(row.points) * ratio, "Round")
			key = f"reverse:{doc.name}:{row.name}"
		elif row.transaction_type == "Redeem":
			points = round_points(-cint(row.points) * total_ratio, "Round")
			key = f"reverse:{row.name}:{doc.name}"
		else:
			continue
		if points <= 0:
			continue

		ledger.lock_account(row.account)
		names, _shortfall = undo_entry(row, key, programme, doc.name, points=points)
		accounts.add(row.account)
		if row.campaign:
			touched.add(row.campaign)
		if row.transaction_type == "Redeem":
			restored_points += sum(cint(frappe.db.get_value(TXN, name, "points")) for name in names)

	_finish(accounts, touched)
	if restored_points and programme:
		_refund_loyalty_tender(doc, flt(restored_points * flt(programme.point_value), 2))


def _refund_loyalty_tender(return_doc, value: float):
	"""Settle the part of a credit note that was paid with points, so staff refund only the rest.

	A 'Pay' Payment Entry from the loyalty liability to the customer's
	receivable, against the credit note. A failure is logged, not raised: the
	points are already restored, and blocking the return would be worse.
	"""
	from excel_restaurant_pos.shared.sales_invoice import fill_required_payment_entry_fields, get_mode_of_payment_account

	mode = loyalty_mode()
	account = get_mode_of_payment_account(mode, return_doc.company) if mode else None
	if not account or value <= 0:
		return

	savepoint = "arcpos_loyalty_refund"
	frappe.db.savepoint(savepoint)
	try:
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Pay"
		pe.posting_date = nowdate()
		pe.mode_of_payment = mode
		pe.party_type = "Customer"
		pe.party = return_doc.customer
		pe.company = return_doc.company
		pe.paid_from = account
		pe.paid_to = return_doc.debit_to
		pe.paid_amount = value
		pe.received_amount = value
		# ERPNext allocates a credit note's negative outstanding as a negative amount.
		pe.append("references", {"reference_doctype": INVOICE, "reference_name": return_doc.name, "allocated_amount": -value})
		pe.remarks = _("Loyalty points restored for credit note {0}").format(return_doc.name)
		fill_required_payment_entry_fields(pe, return_doc)
		pe.flags.ignore_permissions = True
		pe.insert()
		pe.submit()
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(
			title="Loyalty refund payment failed",
			message=(
				f"Credit note {return_doc.name}: {value} was restored as points but no Payment Entry recorded it. "
				f"Refund that much less to the customer, or book it by hand.\n\n{frappe.get_traceback()}"
			),
		)
