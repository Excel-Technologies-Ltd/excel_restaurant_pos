# Copyright (c) 2026, Excel and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.patches.v1_11_0 import move_web_customers_off_sales_user as patch
from excel_restaurant_pos.shared import customer_access
from excel_restaurant_pos.shared.web_customer import (
	WEB_CUSTOMER_READS,
	WEB_CUSTOMER_ROLE,
	ensure_web_customer_role,
	web_customer_roles,
)

LEGACY, NEW, STAFF = "role.legacy@example.com", "role.narrow@example.com", "role.staff@example.com"
WRITES = ("write", "create", "submit", "cancel", "delete", "amend")


def _user(email, *roles):
	user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Role", "user_type": "Website User"})
	user.flags.no_welcome_mail = True
	user.insert(ignore_permissions=True)
	user.add_roles(*roles)
	return user


class TestTheRole(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_web_customer_role()
		_user(NEW, *web_customer_roles())

	def test_it_does_not_open_desk(self):
		self.assertFalse(frappe.db.get_value("Role", WEB_CUSTOMER_ROLE, "desk_access"))
		self.assertEqual(frappe.db.get_value("User", NEW, "user_type"), "Website User")

	def test_it_only_reads(self):
		for doctype in WEB_CUSTOMER_READS:
			perm = frappe.db.get_value(
				"Custom DocPerm", {"parent": doctype, "role": WEB_CUSTOMER_ROLE, "permlevel": 0}, ["read", *WRITES], as_dict=True
			)
			self.assertEqual(perm.read, 1, doctype)
			self.assertFalse(any(perm[p] for p in WRITES), doctype)

	def test_a_storefront_account_can_read_but_not_create_invoices(self):
		self.assertTrue(frappe.has_permission("Sales Invoice", "read", user=NEW))
		self.assertFalse(frappe.has_permission("Sales Invoice", "create", user=NEW))
		self.assertFalse(frappe.has_permission("Sales Invoice", "submit", user=NEW))

	def test_staff_keep_their_invoice_permissions(self):
		# A custom row on its own would have hidden every standard permission.
		roles = set(frappe.get_all("Custom DocPerm", filters={"parent": "Sales Invoice", "create": 1}, pluck="role"))
		self.assertIn("Accounts User", roles)

	def test_running_it_again_undoes_a_ticked_write(self):
		from frappe.permissions import update_permission_property

		update_permission_property("Sales Invoice", WEB_CUSTOMER_ROLE, 0, "create", 1)
		ensure_web_customer_role()
		self.assertFalse(frappe.db.get_value(
			"Custom DocPerm", {"parent": "Sales Invoice", "role": WEB_CUSTOMER_ROLE, "permlevel": 0}, "create"
		))


class TestWhoTheMigrationMoves(FrappeTestCase):
	def test_a_storefront_account_with_sales_user(self):
		self.assertTrue(patch.is_legacy_web_customer({"Customer", "Sales User", "All", "Guest"}))

	def test_not_one_already_moved(self):
		self.assertFalse(patch.is_legacy_web_customer({"Customer", WEB_CUSTOMER_ROLE, "All"}))

	def test_not_staff_who_also_hold_sales_user(self):
		self.assertFalse(patch.is_legacy_web_customer({"Customer", "Sales User", "Restaurant Cashier", "All"}))

	def test_not_a_salesperson_with_only_sales_user(self):
		self.assertFalse(patch.is_legacy_web_customer({"Sales User", "All", "Desk User"}))


class TestTheMigration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_web_customer_role()
		_user(LEGACY, "Customer", "Sales User")
		_user(STAFF, "Customer", "Sales User", "Restaurant Cashier")

	def test_an_unmoved_customer_is_not_staff_meanwhile(self):
		self.assertFalse(customer_access.is_staff(LEGACY))

	def test_it_moves_storefront_accounts_and_only_them(self):
		self.assertEqual(frappe.db.get_value("User", LEGACY, "user_type"), "System User")

		patch.execute()

		roles = set(frappe.get_roles(LEGACY))
		self.assertIn(WEB_CUSTOMER_ROLE, roles)
		self.assertNotIn("Sales User", roles)
		self.assertEqual(frappe.db.get_value("User", LEGACY, "user_type"), "Website User")
		self.assertFalse(frappe.has_permission("Sales Invoice", "create", user=LEGACY))

		self.assertEqual(set(frappe.get_roles(STAFF)) & {"Sales User", "Restaurant Cashier"}, {"Sales User", "Restaurant Cashier"})
		self.assertNotIn(WEB_CUSTOMER_ROLE, frappe.get_roles(STAFF))

	def test_running_it_twice_changes_nothing_more(self):
		patch.execute()
		self.assertNotIn(LEGACY, patch.accounts_to_move())
