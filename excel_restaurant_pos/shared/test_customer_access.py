# Copyright (c) 2026, Excel and Contributors
# See license.txt

import importlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared import customer_access as access
from excel_restaurant_pos.shared.web_customer import web_customer_roles

ZONE = "_Test Access Zone"
ALICE, BOB, CASHIER = "access.alice@example.com", "access.bob@example.com", "access.cashier@example.com"
TABLE = "_Test Access Table"
ALICE_ORDER, ALICE_TABLE_ORDER = "WEB-TEST-ALICE", "ORD-TEST-TABLE"


def _module(path):
	# Package __init__ files re-export functions under their module names.
	return importlib.import_module(path)


class _AccessCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if frappe.db.exists("DocType", "Zone") and not frappe.db.exists("Zone", ZONE):
			frappe.get_doc({"doctype": "Zone", "excel_zone_name": ZONE}).insert(ignore_permissions=True)
		cls.customers = {}
		for email in (ALICE, BOB):
			cls.customers[email] = cls._web_account(email)
		cls._staff(CASHIER, "Restaurant Cashier")

	@staticmethod
	def _web_account(email):
		customer = frappe.get_doc({
			"doctype": "Customer", "customer_name": email, "email_id": email,
			"customer_type": "Individual", "customer_group": "All Customer Groups",
			"territory": "All Territories", "custom_zone": ZONE,
		}).insert(ignore_permissions=True).name
		user = frappe.get_doc({"doctype": "User", "email": email, "first_name": email, "user_type": "Website User"})
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)
		user.add_roles(*web_customer_roles())
		frappe.get_doc({"doctype": "User Permission", "user": email, "allow": "Customer",
		                "for_value": customer, "is_default": 1, "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)
		return customer

	@staticmethod
	def _staff(email, role):
		user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Cashier"})
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)
		user.add_roles(role)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.form_dict = frappe._dict()

	def as_user(self, user):
		frappe.set_user(user)

	def alice_order(self, table=None, name=ALICE_ORDER):
		return frappe._dict(name=name, customer=self.customers[ALICE], custom_linked_table=table)


class TestIdentity(_AccessCase):
	def test_a_guest_is_asked_to_sign_in(self):
		self.as_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			access.require_login()

	def test_storefront_accounts_are_not_staff(self):
		self.assertFalse(access.is_staff(ALICE))

	def test_an_account_with_a_staff_role_is_staff(self):
		self.assertTrue(access.is_staff(CASHIER))
		self.assertTrue(access.is_staff("Administrator"))

	def test_an_account_maps_to_its_own_customer(self):
		self.assertEqual(access.customer_of(ALICE), self.customers[ALICE])
		self.assertEqual(access.customer_of(BOB), self.customers[BOB])


class TestWhoMayTouchAnOrder(_AccessCase):
	def test_the_owner_has_full_access(self):
		self.as_user(ALICE)
		self.assertEqual(access.access_level(self.alice_order()), access.FULL)

	def test_someone_else_is_refused(self):
		self.as_user(BOB)
		with self.assertRaises(frappe.PermissionError):
			access.access_level(self.alice_order())

	def test_staff_may_act_on_any_order(self):
		self.as_user(CASHIER)
		self.assertEqual(access.access_level(self.alice_order()), access.FULL)

	def test_a_guest_is_asked_to_sign_in_before_anything_is_looked_up(self):
		self.as_user("Guest")
		with patch.object(access.frappe.db, "get_value", wraps=access.frappe.db.get_value) as lookup:
			with self.assertRaises(frappe.AuthenticationError):
				access.access_level("WEB-ANY-NUMBER")
		# Frappe's own error handling reads settings to translate the message;
		# what matters is that no order was looked up.
		orders_read = [c for c in lookup.call_args_list if c.args and c.args[0] == "Sales Invoice"]
		self.assertEqual(orders_read, [])

	def test_another_diner_may_share_a_tables_running_order(self):
		self.as_user(BOB)
		with patch.object(access, "_is_table_running_order", return_value=True):
			self.assertEqual(access.access_level(self.alice_order(table=TABLE), allow_table=True), access.TABLE)

	def test_but_only_where_table_sharing_is_allowed(self):
		# Paying, cancelling, gift cards and receipts do not pass allow_table.
		self.as_user(BOB)
		with patch.object(access, "_is_table_running_order", return_value=True):
			with self.assertRaises(frappe.PermissionError):
				access.access_level(self.alice_order(table=TABLE))

	def test_a_table_order_that_is_no_longer_running_is_not_shared(self):
		self.as_user(BOB)
		with patch.object(access, "_is_table_running_order", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				access.access_level(self.alice_order(table=TABLE), allow_table=True)

	def test_the_running_order_check_reads_the_table(self):
		with patch.object(access.frappe.db, "get_value", return_value=ALICE_TABLE_ORDER):
			self.assertTrue(access._is_table_running_order(self.alice_order(table=TABLE, name=ALICE_TABLE_ORDER)))
			self.assertFalse(access._is_table_running_order(self.alice_order(table=TABLE, name="SOMETHING-ELSE")))
		self.assertFalse(access._is_table_running_order(self.alice_order(table=None)))


class TestPersonalDetails(FrappeTestCase):
	def test_a_table_diner_does_not_see_the_owners_details(self):
		doc = MagicMock()
		doc.as_dict.return_value = {"name": "ORD-1", "grand_total": 30, "items": [1],
		                            "custom_mobile_no": "+15550000", "custom_email_address": "a@b.c",
		                            "custom_customer_full_name": "Alice"}
		seen = access.as_seen_by(doc, access.TABLE)
		self.assertEqual((seen["name"], seen["grand_total"], seen["items"]), ("ORD-1", 30, [1]))
		for field in ("custom_mobile_no", "custom_email_address", "custom_customer_full_name"):
			self.assertIsNone(seen[field])

	def test_the_owner_sees_everything(self):
		doc = MagicMock()
		doc.as_dict.return_value = {"custom_mobile_no": "+15550000"}
		self.assertEqual(access.as_seen_by(doc, access.FULL)["custom_mobile_no"], "+15550000")


class TestEveryOrderEndpointNeedsAnAccount(_AccessCase):
	"""Guests may browse and fill a cart; nothing here."""

	CASES = (
		("excel_restaurant_pos.api.sales_invoice.add_or_update_invoice", "add_or_update_invoice",
		 {"customer": "X", "company": "X", "items": []}),
		("excel_restaurant_pos.api.sales_invoice.add_or_update_invoice", "add_or_update_invoice",
		 {"invoice_name": ALICE_ORDER, "items": []}),
		("excel_restaurant_pos.api.sales_invoice.get_sales_invoice", "get_sales_invoice", {"invoice_name": ALICE_ORDER}),
		("excel_restaurant_pos.api.payments.get_payment_ticket", "get_payment_ticket", {"invoice_number": ALICE_ORDER}),
		("excel_restaurant_pos.api.payments.receipt_payment", "receipt_payment", {"ticket": "T", "order_no": ALICE_ORDER}),
		("excel_restaurant_pos.api.payments.cancel_payment", "cancel_payment", {"ticket": "T", "order_no": ALICE_ORDER}),
		("excel_restaurant_pos.api.payments.check_receipt_status", "check_receipt_status", {"ticket": "T"}),
		("excel_restaurant_pos.api.gift_card.apply_gift_card", "apply_gift_card", {"sales_invoice": ALICE_ORDER}),
		("excel_restaurant_pos.api.gift_card.verify_gift_card", "verify_gift_card", {"gift_card_code": "X"}),
		("excel_restaurant_pos.api.coupon.validate_coupon", "validate_coupon", {"coupon_code": "X"}),
		("excel_restaurant_pos.api.print.invoice_pdf", "invoice_pdf", {"invoice_name": ALICE_ORDER}),
	)

	def test_a_guest_is_refused_by_every_order_endpoint(self):
		for path, fn, form in self.CASES:
			with self.subTest(endpoint=f"{path.split('.')[-1]}.{fn}", form=list(form)):
				self.as_user("Guest")
				frappe.local.form_dict = frappe._dict(form)
				with self.assertRaises(frappe.AuthenticationError):
					getattr(_module(path), fn)()

	def test_the_legacy_coupon_check_needs_an_account(self):
		self.as_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			_module("excel_restaurant_pos.api.item.item").check_coupon_code('{"coupon_code": "X"}')

	def test_legacy_order_creators_are_staff_only(self):
		for path in ("excel_restaurant_pos.api.item.item", "excel_restaurant_pos.api.doordash.doordash"):
			module = _module(path)
			with self.subTest(path=path):
				self.as_user("Guest")
				with self.assertRaises(frappe.AuthenticationError):
					module.create_order() if path.endswith("doordash") else module.create_order("{}")
				self.as_user(ALICE)
				with self.assertRaises(frappe.PermissionError):
					module.create_order() if path.endswith("doordash") else module.create_order("{}")


class TestOrdersArePlacedForTheCaller(_AccessCase):
	MODULE = "excel_restaurant_pos.api.sales_invoice.add_or_update_invoice"

	def _capture_customer(self, body_customer):
		"""The customer a new order would be placed for, stopping before any write."""
		module = _module(self.MODULE)
		captured = {}

		def stop(data):
			captured["customer"] = data.get("customer")
			raise RuntimeError("stop before insert")

		frappe.local.form_dict = frappe._dict(customer=body_customer, company="X", items=[])
		with patch.object(module, "_validate_required_fields", side_effect=stop), \
			patch.object(module, "check_order_honeypot"), patch.object(module, "verify_order_turnstile"):
			with self.assertRaises(RuntimeError):
				module.add_or_update_invoice()
		return captured["customer"]

	def test_a_customer_cannot_order_as_someone_else(self):
		"""The storefront used to choose the customer; now the account does."""
		self.as_user(ALICE)
		self.assertEqual(self._capture_customer(self.customers[BOB]), self.customers[ALICE])

	def test_staff_may_still_name_the_customer(self):
		self.as_user(CASHIER)
		self.assertEqual(self._capture_customer(self.customers[BOB]), self.customers[BOB])

	def test_another_diner_adding_to_a_table_order_gets_no_personal_details(self):
		module = _module(self.MODULE)
		self.as_user(BOB)
		updated = MagicMock()
		updated.as_dict.return_value = {"name": ALICE_TABLE_ORDER, "custom_mobile_no": "+15550000"}
		frappe.local.form_dict = frappe._dict(invoice_name=ALICE_TABLE_ORDER, items=[{"item_code": "X"}])
		with patch.object(module, "access_level", return_value=access.TABLE), \
			patch.object(module, "update_sales_invoice", return_value=updated):
			result = module.add_or_update_invoice()
		self.assertEqual(result["name"], ALICE_TABLE_ORDER)
		self.assertIsNone(result["custom_mobile_no"])

	def test_another_diner_cannot_submit_the_table_order(self):
		module = _module(self.MODULE)
		self.as_user(BOB)
		frappe.local.form_dict = frappe._dict(invoice_name=ALICE_TABLE_ORDER, items=[], docstatus=1)
		with patch.object(module, "access_level", return_value=access.TABLE), \
			patch.object(module, "update_sales_invoice") as update:
			with self.assertRaises(frappe.PermissionError):
				module.add_or_update_invoice()
		update.assert_not_called()


class TestProtectionsStillApplyToSignedInCustomers(_AccessCase):
	def test_turnstile_now_challenges_a_signed_in_customer(self):
		from excel_restaurant_pos.shared.antispam import turnstile

		self.as_user(ALICE)
		with patch.dict(frappe.conf, {turnstile.SECRET_CONFIG_KEY: "0x-secret"}), \
			patch.object(turnstile.frappe, "log_error"), patch.object(turnstile, "_siteverify") as verify:
			with self.assertRaises(frappe.ValidationError):
				turnstile.verify_order_turnstile(frappe._dict())  # no token
		verify.assert_not_called()

	def test_turnstile_still_leaves_staff_alone(self):
		from excel_restaurant_pos.shared.antispam import turnstile

		self.as_user(CASHIER)
		with patch.dict(frappe.conf, {turnstile.SECRET_CONFIG_KEY: "0x-secret"}):
			turnstile.verify_order_turnstile(frappe._dict())

	def test_a_signed_in_customer_is_rate_limited_per_account(self):
		from excel_restaurant_pos.utils import rate_limit

		method = "api.sales_invoices.add"
		limit, _seconds = rate_limit.STRICT_WRITE_LIMITS[method]
		frappe.cache().delete_keys("arcpos:rate:customer_api:*")
		self.addCleanup(frappe.cache().delete_keys, "arcpos:rate:customer_api:*")

		self.as_user(ALICE)
		for _ in range(limit):
			rate_limit._limit_signed_in_customer(method)
		with self.assertRaises(frappe.ValidationError):
			rate_limit._limit_signed_in_customer(method)

		# Bob has his own budget.
		self.as_user(BOB)
		rate_limit._limit_signed_in_customer(method)

	def test_staff_are_not_rate_limited(self):
		from excel_restaurant_pos.utils import rate_limit

		self.as_user(CASHIER)
		for _ in range(50):
			rate_limit._limit_signed_in_customer("api.sales_invoices.add")
