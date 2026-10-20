"""Points as tender on an order.

Points are a payment method, not a discount: `discount_amount` already
belongs to the promo coupon or the gift cards, and tender combines naturally
with card or cash on the same order. Tax is computed on the full order.

Flow:
- apply / remove on a draft only set the invoice fields; nothing is spent.
- validate re-checks the limits on every save and clamps when the order shrank.
- before_submit locks the account, re-reads the ledger and posts the Redeem
  entry inside the submit transaction -- a failed submit rolls it back, and of
  two drafts racing for the same points the second fails here.
- a card checkout holds its points from its payment ticket until it submits,
  and a card-paid order always submits (holds.py).
- on_submit books the tender: a Payment Entry in the loyalty Mode of Payment
  (Dr loyalty liability, Cr debtors). ArcPOS invoices are not POS invoices,
  so their payments are Payment Entries; a POS invoice gets a payments row.
"""

from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.utils import cint, flt

from excel_restaurant_pos.shared.loyalty import holds, ledger
from excel_restaurant_pos.shared.loyalty.accounts import account_for_customer
from excel_restaurant_pos.shared.loyalty.settings import (
	ACCOUNT,
	channel_allowed,
	channel_key,
	get_active_programme,
	get_settings,
	is_enabled,
)

INVOICE = "Sales Invoice"
POINTS_FIELD = "custom_loyalty_points_redeemed"
VALUE_FIELD = "custom_loyalty_redeem_value"
ACCOUNT_FIELD = "custom_loyalty_account"
VERIFIED_FIELD = "custom_loyalty_verified"
TOLERANCE = 0.01


def loyalty_mode() -> str | None:
	settings = get_settings()
	return settings.loyalty_mode_of_payment if settings else None


def _number(doc, fieldname) -> float:
	"""A numeric field, or 0 when the invoice (or a stand-in for one) has none."""
	value = doc.get(fieldname) if isinstance(doc, dict) else getattr(doc, fieldname, None)
	if isinstance(value, bool) or not isinstance(value, (int, float, str)):
		return 0.0
	return flt(value)


def redeemed_value(doc) -> float:
	return _number(doc, VALUE_FIELD) if _number(doc, POINTS_FIELD) else 0.0


def amount_due(invoice) -> float:
	"""What is still to be collected by other tenders once points are applied."""
	return max(_number(invoice, "grand_total") - redeemed_value(invoice), 0.0)


def _due_for_points(doc) -> float:
	# A draft, or one being submitted right now, owes its full total -- its own
	# loyalty row (POS) must not shrink the room for the points it pays.
	if cint(doc.get("docstatus")) == 0 or getattr(doc, "_action", None) == "submit":
		return flt(doc.get("grand_total"))
	return flt(doc.get("outstanding_amount"))


def options(doc, account: str | None = None, programme=None, available: int | None = None) -> dict:
	"""Min, max, step and value per point for this order and member.

	`available` overrides the ledger balance (the submit-time check passes the
	applied points, so only the order's own limits are applied).
	"""
	programme = programme or get_active_programme(doc.get("posting_date"))
	account = account or account_for_customer(doc.get("customer"))
	empty = {
		"redeemable": False,
		"available_points": 0,
		"min_points": 0,
		"max_points": 0,
		"step": 1,
		"point_value": flt(programme.point_value) if programme else 0,
		"max_value": 0,
		"account": account,
	}
	if not programme or not account:
		return empty

	point_value = flt(programme.point_value)
	if point_value <= 0:
		return empty

	if available is None:
		# Less what other orders' card checkouts hold (shared/loyalty/holds.py).
		available = holds.spendable(account, exclude_invoice=doc.get("name"))
	available = max(cint(available), 0)
	step = max(cint(programme.redeem_increment), 1)
	cap_percent = flt(programme.max_redeem_percent_of_order) or 100
	value_cap = min(flt(doc.get("grand_total")) * cap_percent / 100, _due_for_points(doc))

	max_points = min(available, int(math.floor(value_cap / point_value + 1e-9)))
	if cint(programme.max_redeem_points_per_order):
		max_points = min(max_points, cint(programme.max_redeem_points_per_order))
	max_points = max((max_points // step) * step, 0)
	min_points = int(math.ceil(max(cint(programme.min_redeem_points), step) / step)) * step

	return {
		"redeemable": max_points >= min_points and max_points > 0,
		"available_points": available,
		"min_points": min_points,
		"max_points": max_points,
		"step": step,
		"point_value": point_value,
		"max_value": flt(max_points * point_value, 2),
		"account": account,
	}


def _clear(doc):
	doc.set(POINTS_FIELD, 0)
	doc.set(VALUE_FIELD, 0)
	if doc.meta.has_field(VERIFIED_FIELD):
		doc.set(VERIFIED_FIELD, 0)
	_remove_pos_row(doc)


def _remove_pos_row(doc):
	mode = loyalty_mode()
	if not mode or not cint(doc.get("is_pos")):
		return
	rows = [row for row in doc.get("payments") or [] if row.mode_of_payment != mode]
	if len(rows) != len(doc.get("payments") or []):
		doc.set("payments", rows)
		doc.calculate_taxes_and_totals()


def _upsert_pos_row(doc, value):
	mode = loyalty_mode()
	if not mode or not cint(doc.get("is_pos")):
		return
	row = next((r for r in doc.get("payments") or [] if r.mode_of_payment == mode), None)
	if not row:
		row = doc.append("payments", {"mode_of_payment": mode})
	row.amount = value
	doc.calculate_taxes_and_totals()


def assert_configured(company: str):
	from excel_restaurant_pos.shared.sales_invoice import get_mode_of_payment_account

	mode = loyalty_mode()
	if not mode:
		frappe.throw(_("Set the Loyalty Mode of Payment in ArcPOS Loyalty Settings."))
	if not get_mode_of_payment_account(mode, company):
		frappe.throw(_("Mode of Payment {0} has no account for company {1}.").format(mode, company))


def _check_order(doc, account: str, programme):
	if not programme:
		frappe.throw(_("The loyalty programme is not active."))
	status, customer = frappe.db.get_value(ACCOUNT, account, ["status", "customer"])
	if status != "Active":
		frappe.throw(_("Loyalty account {0} is {1}.").format(account, (status or "").lower()))
	if customer != doc.customer:
		frappe.throw(_("This loyalty account does not belong to the order's customer."), frappe.PermissionError)
	if not channel_allowed(programme, "redeem", channel_key(doc)):
		frappe.throw(_("Loyalty points cannot be used for this order type."))
	if cint(doc.get("is_return")):
		frappe.throw(_("Loyalty points cannot be used on a return."))


def _check_points(points: int, opts: dict):
	if points <= 0:
		frappe.throw(_("Enter the number of points to use."))
	if points % opts["step"]:
		frappe.throw(_("Points must be used in multiples of {0}.").format(opts["step"]))
	if points < opts["min_points"]:
		frappe.throw(_("At least {0} points must be used.").format(opts["min_points"]))
	if points > opts["max_points"]:
		frappe.throw(
			_("At most {0} points can be used on this order ({1} available).").format(
				opts["max_points"], opts["available_points"]
			)
		)


def summary(doc) -> dict:
	return {
		"sales_invoice": doc.name,
		"points": cint(doc.get(POINTS_FIELD)),
		"value": flt(doc.get(VALUE_FIELD)),
		"grand_total": flt(doc.grand_total),
		"amount_due": amount_due(doc) if cint(doc.docstatus) == 0 else flt(doc.get("outstanding_amount")),
		"account": doc.get(ACCOUNT_FIELD),
	}


def apply_points(invoice: str, points) -> dict:
	"""Put points against an order: on a draft as pending tender, on a submitted one at once."""
	if not is_enabled():
		frappe.throw(_("Loyalty is not enabled."))
	doc = frappe.get_doc(INVOICE, invoice)
	if cint(doc.docstatus) == 2:
		frappe.throw(_("Order {0} was cancelled.").format(doc.name))

	points = cint(points)
	programme = get_active_programme(doc.posting_date)
	account = account_for_customer(doc.customer)
	if not account:
		frappe.throw(_("The order's customer is not a loyalty member."))
	_check_order(doc, account, programme)
	assert_configured(doc.company)

	if cint(doc.docstatus) == 1:
		return _redeem_submitted(doc, account, points, programme)

	opts = options(doc, account, programme)
	_check_points(points, opts)
	doc.set(POINTS_FIELD, points)
	doc.set(VALUE_FIELD, flt(points * opts["point_value"], 2))
	doc.set(ACCOUNT_FIELD, account)
	doc.save(ignore_permissions=True)
	_discard_payment_tickets(doc.name)
	return summary(doc)


def remove_points(invoice: str) -> dict:
	doc = frappe.get_doc(INVOICE, invoice)
	if cint(doc.docstatus) != 0:
		frappe.throw(_("Points can only be removed from a draft order."))
	_clear(doc)
	doc.save(ignore_permissions=True)
	_discard_payment_tickets(doc.name)
	return summary(doc)


def _discard_payment_tickets(invoice: str):
	"""A gateway ticket preloaded at the old amount would now be refused as a mismatch."""
	from excel_restaurant_pos.shared.payment_ticket import discard_tickets

	discard_tickets(invoice)


def _redeem_submitted(doc, account: str, points: int, programme) -> dict:
	"""A dine-in order sent to the kitchen (submitted) before it is paid."""
	if ledger.find_by_key(f"redeem:{doc.name}"):
		frappe.throw(_("Points have already been used on this order."))

	locked = ledger.lock_account(account)
	opts = options(doc, account, programme)
	_check_points(points, opts)

	from excel_restaurant_pos.shared.loyalty import otp

	otp.assert_step_up(account, doc, points)

	value = flt(points * opts["point_value"], 2)
	_post_redeem(locked, doc, points)
	frappe.db.set_value(
		INVOICE, doc.name, {POINTS_FIELD: points, VALUE_FIELD: value, ACCOUNT_FIELD: account}, update_modified=False
	)
	create_loyalty_payment(doc.name, value)
	_after_redeem(account, doc.name, points, value)
	doc.reload()
	return summary(doc)


def _post_redeem(locked, doc, points: int):
	# The card has already been charged for the rest of the order: refusing
	# now would strand a paid order. A shortfall becomes a debt instead.
	paid = holds.paid_by_card(doc.name)
	if not paid:
		holds.assert_spendable(locked.name, points, exclude_invoice=doc.name)
	try:
		ledger.post_debit(
			locked,
			"Redeem",
			points,
			f"redeem:{doc.name}",
			allow_negative=paid,
			source_doctype=INVOICE,
			source_name=doc.name,
		)
	except ledger.InsufficientPoints as exc:
		frappe.throw(str(exc), title=_("Loyalty Points"))


def _after_redeem(account: str, invoice: str, points: int, value: float):
	ledger.recompute_cache(account, touch_activity=True)
	from excel_restaurant_pos.shared.loyalty.notifications import enqueue_notification

	enqueue_notification(
		account, "redeemed", key=f"redeemed:{invoice}", context={"points": points, "value": value, "invoice": invoice}
	)


# ---------------------------------------------------------------- hooks


def validate_invoice_redemption(doc, method=None):
	"""Sales Invoice validate: keep applied points within the limits of the current order."""
	points = cint(doc.get(POINTS_FIELD))
	if not points:
		if flt(doc.get(VALUE_FIELD)):
			doc.set(VALUE_FIELD, 0)
		# An account stamped for a customer the order no longer has (points
		# removed, then the customer changed) must not follow the order.
		stamped = doc.get(ACCOUNT_FIELD)
		if stamped and frappe.db.get_value(ACCOUNT, stamped, "customer") != doc.customer:
			doc.set(ACCOUNT_FIELD, None)
		return

	if cint(doc.get("is_return")) or not is_enabled():
		_clear(doc)
		return

	programme = get_active_programme(doc.posting_date)
	account = account_for_customer(doc.customer)
	if not programme or not account or (doc.get(ACCOUNT_FIELD) and doc.get(ACCOUNT_FIELD) != account):
		frappe.msgprint(_("Loyalty points were removed from this order."), alert=True)
		_clear(doc)
		return

	_check_order(doc, account, programme)
	# On submit the balance is checked under the account lock in
	# post_redemption, which refuses clearly; clamping here would quietly drop
	# points another order spent first.
	submitting = getattr(doc, "_action", None) == "submit"
	opts = options(doc, account, programme, available=points if submitting else None)
	if points > opts["max_points"]:
		points = opts["max_points"]
		frappe.msgprint(_("Loyalty points on this order were reduced to {0}.").format(points), alert=True)
	points = (points // opts["step"]) * opts["step"]
	if points < opts["min_points"] or points <= 0:
		frappe.msgprint(_("Loyalty points were removed from this order."), alert=True)
		_clear(doc)
		return

	value = flt(points * opts["point_value"], 2)
	doc.set(POINTS_FIELD, points)
	doc.set(VALUE_FIELD, value)
	doc.set(ACCOUNT_FIELD, account)
	_upsert_pos_row(doc, value)

	if cint(doc.get("custom_with_arcpos_payment")) and not cint(doc.get("is_pos")):
		mode = loyalty_mode()
		other = sum(flt(row.amount) for row in doc.get("payments") or [] if row.mode_of_payment != mode)
		if other + value > flt(doc.grand_total) + TOLERANCE:
			frappe.throw(
				_("Payments ({0}) plus loyalty points ({1}) exceed the order total ({2}).").format(
					frappe.format_value(other, {"fieldtype": "Currency"}),
					frappe.format_value(value, {"fieldtype": "Currency"}),
					frappe.format_value(doc.grand_total, {"fieldtype": "Currency"}),
				)
			)


def post_redemption(doc, method=None):
	"""Sales Invoice before_submit: spend the points, under the account lock."""
	points = cint(doc.get(POINTS_FIELD))
	if not points:
		return
	assert_configured(doc.company)
	account = doc.get(ACCOUNT_FIELD)
	locked = ledger.lock_account(account)
	if locked.status != "Active":
		frappe.throw(_("Loyalty account {0} is {1}.").format(account, (locked.status or "").lower()))

	from excel_restaurant_pos.shared.loyalty import otp

	otp.assert_step_up(account, doc, points)
	_post_redeem(locked, doc, points)


def on_submit_redemption(doc, method=None):
	"""Sales Invoice on_submit: book the points tender and refresh the member."""
	points = cint(doc.get(POINTS_FIELD))
	if not points:
		return
	value = flt(doc.get(VALUE_FIELD))
	if not _pos_row_booked(doc):
		create_loyalty_payment(doc.name, value)
	_after_redeem(doc.get(ACCOUNT_FIELD), doc.name, points, value)


def _pos_row_booked(doc) -> bool:
	"""Whether ERPNext's own POS payment rows already book the points tender.

	It books a POS invoice's rows only when they were priced on a save: a
	draft saved and then submitted. An invoice whose rows first arrive with
	the submit itself (pos-web) is never priced, so its rows book nothing,
	ArcPOS's create_payment_entry books the rest less the loyalty row, and
	the points tender is this module's to book.
	"""
	if not cint(doc.get("is_pos")):
		return False
	mode = loyalty_mode()
	return any(row.mode_of_payment == mode and flt(row.base_amount) for row in doc.get("payments") or [])


def loyalty_payment_entries(invoice: str, docstatus: int = 1) -> list[str]:
	mode = loyalty_mode()
	if not mode:
		return []
	return frappe.db.sql(
		"""
		SELECT DISTINCT pe.name
		FROM `tabPayment Entry` pe
		JOIN `tabPayment Entry Reference` ref ON ref.parent = pe.name
		WHERE ref.reference_doctype = 'Sales Invoice' AND ref.reference_name = %s
			AND pe.mode_of_payment = %s AND pe.docstatus = %s
		""",
		(invoice, mode, docstatus),
		pluck=True,
	)


def create_loyalty_payment(invoice: str, value: float):
	"""Book the points tender as a Payment Entry. Idempotent per invoice."""
	if flt(value) <= 0 or loyalty_payment_entries(invoice):
		return
	from excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry import create_payment_entry

	created = create_payment_entry(
		sales_invoice=invoice, payments=[{"mode_of_payment": loyalty_mode(), "amount": flt(value, 2)}]
	)
	if not created:
		frappe.throw(_("Could not record the loyalty points payment. Check the Loyalty Mode of Payment account."))
