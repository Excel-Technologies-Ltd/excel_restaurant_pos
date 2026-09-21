"""Move storefront accounts from Sales User to the narrow ArcPOS Web Customer role.

Sales User lets a customer create and submit Sales Invoices through Frappe's
generic API and makes them a System User with Desk access; see
shared/web_customer.py. New accounts already get the narrow role -- this moves
the ones made before it existed.

Only accounts that are plainly storefront customers are touched: every role they
hold, apart from the automatic ones, is a storefront role or Sales User, and
they hold the default web role. Staff with Sales User alongside a staff role,
and salespeople with Sales User alone, are left alone.
Saving the User recomputes its type, so a moved account becomes a Website User.
"""

import frappe

from excel_restaurant_pos.shared.customer_access import AUTOMATIC_ROLES
from excel_restaurant_pos.shared.web_customer import (
	WEB_CUSTOMER_ROLE,
	ensure_web_customer_role,
	web_customer_roles,
)

LEGACY_ROLE = "Sales User"


def is_legacy_web_customer(roles):
	"""True for a storefront account still carrying Sales User, and nothing else.

	The default web role (Customer) is what marks a storefront account; an
	account holding only Sales User is a salesperson and stays as it is.
	"""
	roles = set(roles) - AUTOMATIC_ROLES
	storefront = set(web_customer_roles())
	default_role = web_customer_roles()[0]
	return LEGACY_ROLE in roles and default_role in roles and roles <= storefront | {LEGACY_ROLE}


def accounts_to_move():
	rows = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "parent": ["not in", ["Administrator", "Guest"]]},
		fields=["parent", "role"],
	)
	roles_by_user = {}
	for row in rows:
		roles_by_user.setdefault(row.parent, set()).add(row.role)
	return sorted(user for user, roles in roles_by_user.items() if is_legacy_web_customer(roles))


def execute():
	# The role must exist before anyone is given it; after_migrate runs too late.
	ensure_web_customer_role()

	for name in accounts_to_move():
		user = frappe.get_doc("User", name)
		user.flags.ignore_permissions = True
		user.flags.no_welcome_mail = True
		user.append_roles(WEB_CUSTOMER_ROLE)
		user.remove_roles(LEGACY_ROLE)  # saves once, with both changes
