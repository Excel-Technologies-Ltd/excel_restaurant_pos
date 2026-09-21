"""How many orders one customer may place in an hour.

Set in ArcPOS Settings > Website > "Max Orders per Customer per Hour"; 0 turns
the limit off. Staff placing orders at the POS are never limited -- the caller
decides that, since only it knows who is asking.

Every order the customer created in the last hour counts, paid or not: an
unpaid "Pay First" order is exactly what a spammer leaves behind.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

SETTINGS_DOCTYPE = "ArcPOS Settings"
SETTINGS_FIELD = "max_orders_per_customer_per_hour"
DEFAULT_LIMIT = 5
WINDOW_HOURS = 1


def hourly_limit():
	"""The configured limit; 0 means none."""
	return cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, SETTINGS_FIELD))


def orders_in_window(customer):
	return frappe.db.count(
		"Sales Invoice",
		{"customer": customer, "creation": [">=", add_to_date(now_datetime(), hours=-WINDOW_HOURS)]},
	)


def check_customer_order_limit(customer):
	"""Refuse a new order once this customer has reached the hourly limit."""
	limit = hourly_limit()
	if limit <= 0 or not customer:
		return

	placed = orders_in_window(customer)
	if placed < limit:
		return

	frappe.log_error(
		title="Order refused: customer hourly limit",
		message=f"customer={customer} orders_last_hour={placed} limit={limit} user={frappe.session.user}",
	)
	frappe.throw(
		_("You have placed {0} orders in the last hour, the most we accept. Please try again later or call us.").format(
			placed
		),
		frappe.ValidationError,
	)
