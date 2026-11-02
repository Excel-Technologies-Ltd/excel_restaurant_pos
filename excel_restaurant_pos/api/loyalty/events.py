"""Fire any loyalty event type for a customer from another system."""

import frappe
from frappe import _

from excel_restaurant_pos.shared.loyalty.events import emit as emit_event
from excel_restaurant_pos.shared.loyalty.settings import LOYALTY_MANAGER
from excel_restaurant_pos.utils.error_handler import success_response


@frappe.whitelist(methods=["POST"])
def emit(event_code=None, customer=None, reference=None, payload=None):
	"""`reference` is required: it is the idempotency key, so a retried call awards once."""
	frappe.only_for([LOYALTY_MANAGER, "System Manager"])
	if not event_code or not customer or not reference:
		frappe.throw(_("event_code, customer and reference are required."), frappe.ValidationError)
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer), frappe.DoesNotExistError)

	entries = emit_event(
		event_code,
		customer,
		payload=frappe.parse_json(payload) if isinstance(payload, str) else (payload or {}),
		reference_key=str(reference)[:100],
	)
	frappe.db.commit()
	points = sum(frappe.db.get_value("ArcPOS Loyalty Transaction", name, "points") or 0 for name in entries)
	return success_response(_("Event processed"), data={"entries": entries, "points": points})
