"""Who may create, pay for, discount or read an order.

Ordering requires an account. Browsing the menu, reading a table's name from its
QR code and building a cart do not; everything that creates, pays for,
discounts or reads an order does.

Signing in is not enough on its own. The storefront used to tell the server
which customer an order was for; now the server decides from the account, and
every later call on an order checks it belongs to the caller. So nobody can
order as, pay for, cancel, discount or read someone else's order.

The one exception is a table. A table's running order (Restaurant
Table.running_order) is shared: everyone at the table adds to it from their own
phone. Any signed-in diner may add items to it and read it back -- with the
owner's personal details removed. Paying, cancelling, gift cards and receipts
stay with the owner.

Staff are never restricted here; they are identified by holding any role beyond
the ones a storefront account is given.

Refusals for a caller who is not signed in are AuthenticationError (401), not
PermissionError (403): the storefront refreshes its token and retries on a 401,
so an expired login recovers by itself instead of stranding the customer.
"""

import frappe
from frappe import _

from excel_restaurant_pos.shared.web_customer import web_customer_roles

INVOICE_DOCTYPE = "Sales Invoice"

# Roles every account carries automatically; they say nothing about staff.
AUTOMATIC_ROLES = {"All", "Guest", "Desk User"}

FULL, TABLE = "full", "table"

# Blanked for a diner reading someone else's table order. Personal details of
# whoever opened the order, not anything about the food.
PERSONAL_FIELDS = (
	"customer_name",
	"custom_customer_full_name",
	"custom_mobile_no",
	"custom_email_address",
	"contact_person",
	"contact_display",
	"contact_mobile",
	"contact_email",
	"customer_address",
	"address_display",
	"shipping_address_name",
	"shipping_address",
	"custom_delivery_location",
	"custom_address_instruction",
	"custom_pincode",
)


def current_user():
	return frappe.session.user if frappe.session else "Guest"


def require_login():
	"""The signed-in user, or a 401 for anyone who is not."""
	user = current_user()
	if not user or user == "Guest":
		frappe.throw(_("Please sign in to continue."), frappe.AuthenticationError)
	return user


def is_staff(user=None):
	"""Anyone holding more than the roles a storefront account is given."""
	user = user or current_user()
	if not user or user == "Guest":
		return False
	if user == "Administrator":
		return True

	extra = set(frappe.get_roles(user)) - set(web_customer_roles()) - AUTOMATIC_ROLES
	return bool(extra)


def customer_of(user):
	"""The Customer a storefront account is restricted to, if any."""
	for filters in (
		{"user": user, "allow": "Customer", "is_default": 1},
		{"user": user, "allow": "Customer"},
	):
		customer = frappe.db.get_value("User Permission", filters, "for_value")
		if customer:
			return customer

	email = frappe.db.get_value("User", user, "email")
	return frappe.db.get_value("Customer", {"email_id": email}, "name") if email else None


def own_customer_or_refuse(user):
	"""The Customer a new order is placed for, decided by the server."""
	customer = customer_of(user)
	if not customer:
		frappe.throw(
			_("Your account is not linked to a customer yet. Please contact the restaurant."),
			frappe.ValidationError,
		)
	return customer


def _is_table_running_order(invoice):
	table = invoice.get("custom_linked_table")
	if not table:
		return False
	return frappe.db.get_value("Restaurant Table", table, "running_order") == invoice.get("name")


def access_level(invoice, allow_table=False):
	"""FULL or TABLE for the caller on `invoice`, or a refusal.

	`invoice` is a Sales Invoice document or dict, or its name.
	"""
	user = require_login()

	# Staff may act on any order, so there is nothing to look up for them.
	if is_staff(user):
		return FULL

	if isinstance(invoice, str):
		invoice = frappe.db.get_value(
			INVOICE_DOCTYPE, invoice, ["name", "customer", "custom_linked_table"], as_dict=True
		)
		if not invoice:
			frappe.throw(_("Order not found"), frappe.DoesNotExistError)

	owner = customer_of(user)
	if owner and invoice.get("customer") == owner:
		return FULL

	if allow_table and _is_table_running_order(invoice):
		return TABLE

	frappe.throw(_("This order does not belong to your account."), frappe.PermissionError)


def as_seen_by(invoice_doc, level):
	"""The invoice as a dict, with the owner's details removed for a TABLE reader."""
	data = invoice_doc.as_dict()
	if level == TABLE:
		for fieldname in PERSONAL_FIELDS:
			if fieldname in data:
				data[fieldname] = None
	return data
