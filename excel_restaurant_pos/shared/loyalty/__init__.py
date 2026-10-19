"""ArcPOS customer loyalty programme.

The ledger (ArcPOS Loyalty Transaction) is the single source of truth;
account balances and wallet passes are views of it. Everything is a no-op
while ArcPOS Loyalty Settings.enabled is off.

Public facade -- imported lazily so loading this package pulls in nothing.
"""

from frappe.utils import cint


def enrol(customer, source="Admin", user=None):
	from excel_restaurant_pos.shared.loyalty.accounts import enrol as _enrol

	return _enrol(customer, source=source, user=user)


def emit(event_code, customer, reference_doctype=None, reference_name=None, payload=None, reference_key=None):
	from excel_restaurant_pos.shared.loyalty.events import emit as _emit

	return _emit(event_code, customer, reference_doctype, reference_name, payload, reference_key)


def award_for_invoice(invoice):
	from excel_restaurant_pos.shared.loyalty.earning import award_for_invoice as _award

	return _award(invoice)


def schedule_sync(account, force=False):
	from excel_restaurant_pos.shared.loyalty.wallet.sync import schedule_sync as _schedule

	return _schedule(account, force=force)


def disable_native_loyalty(doc, method=None):
	"""Sales Invoice validate: ERPNext's own loyalty never runs on ArcPOS invoices.

	Left on, a customer enrolled in an ERPNext Loyalty Program would earn
	twice for one order. With ArcPOS loyalty switched off nothing is changed:
	`enabled = 0` means no loyalty behaviour of ours at all.
	"""
	from excel_restaurant_pos.shared.loyalty.settings import is_enabled

	if not is_enabled():
		return
	doc.dont_create_loyalty_points = 1
	if cint(doc.get("redeem_loyalty_points")):
		doc.redeem_loyalty_points = 0
		doc.loyalty_points = 0
		doc.loyalty_amount = 0
