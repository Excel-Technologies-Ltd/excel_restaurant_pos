# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.sales_invoice import idempotency

MODULE = "excel_restaurant_pos.shared.sales_invoice.idempotency"


class TestReadKey(FrappeTestCase):
	def setUp(self):
		frappe.local.form_dict = frappe._dict(cmd="api.sales_invoices.add")

		# A web request has to look present or the header is never consulted.
		previous = getattr(frappe.local, "request", None)
		frappe.local.request = MagicMock()
		self.addCleanup(setattr, frappe.local, "request", previous)

		patcher = patch(f"{MODULE}.frappe.get_request_header", return_value=None)
		self.header = patcher.start()
		self.addCleanup(patcher.stop)

	def test_no_request_means_no_header(self):
		"""Called from a background job, reading frappe.request would raise."""
		frappe.local.request = None
		self.assertIsNone(idempotency.read_key(frappe._dict()))

	def test_no_key_is_not_an_error(self):
		"""Existing clients send nothing and must keep working."""
		self.assertIsNone(idempotency.read_key(frappe._dict()))

	def test_the_header_is_read(self):
		self.header.return_value = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
		self.assertEqual(
			idempotency.read_key(frappe._dict()), "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
		)

	def test_the_body_is_a_fallback(self):
		for body_key in idempotency.IDEMPOTENCY_BODY_KEYS:
			with self.subTest(key=body_key):
				data = frappe._dict({body_key: "checkout-abc12345"})
				self.assertEqual(idempotency.read_key(data), "checkout-abc12345")

	def test_the_header_wins_over_the_body(self):
		self.header.return_value = "from-the-header-1"
		data = frappe._dict(idempotency_key="from-the-body-01")
		self.assertEqual(idempotency.read_key(data), "from-the-header-1")

	def test_whitespace_is_trimmed(self):
		self.assertEqual(
			idempotency.read_key(frappe._dict(idempotency_key="  abcdefgh  ")), "abcdefgh"
		)

	def test_a_junk_key_is_refused(self):
		for bad in ("short", "x" * 129, "has spaces here", "semi;colon", "quote'here", "../etc"):
			with self.subTest(key=bad):
				with self.assertRaises(frappe.ValidationError):
					idempotency.read_key(frappe._dict(idempotency_key=bad))


class TestSaveOnce(FrappeTestCase):
	"""The database is the guarantee, not the lookup that precedes it."""

	def setUp(self):
		patcher = patch(f"{MODULE}.supported", return_value=True)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _invoice(self):
		invoice = MagicMock()
		invoice.name = "WEB-26-02021"
		return invoice

	@patch(f"{MODULE}.frappe.db")
	def test_a_first_request_just_saves(self, db):
		invoice = self._invoice()

		saved, replayed = idempotency.save_once(invoice, "checkout-abc12345")

		invoice.save.assert_called_once_with(ignore_permissions=True)
		self.assertIs(saved, invoice)
		self.assertFalse(replayed)

	@patch(f"{MODULE}.find_invoice")
	@patch(f"{MODULE}.frappe.db")
	def test_a_concurrent_retry_gets_the_winners_order(self, db, find_invoice):
		# Both requests looked, both saw nothing, both tried to insert. Only one
		# row can carry the key, so the loser has to return the winner's order.
		invoice = self._invoice()
		invoice.save.side_effect = frappe.DuplicateEntryError
		winner = self._invoice()
		winner.name = "WEB-26-02020"
		find_invoice.return_value = winner

		saved, replayed = idempotency.save_once(invoice, "checkout-abc12345")

		self.assertIs(saved, winner)
		self.assertTrue(replayed)

	@patch(f"{MODULE}.find_invoice")
	@patch(f"{MODULE}.frappe.db")
	def test_the_transaction_is_rolled_back_before_the_lookup(self, db, find_invoice):
		# A failed insert poisons the transaction; the lookup after it would
		# fail too without rolling back to the savepoint first.
		invoice = self._invoice()
		invoice.save.side_effect = frappe.UniqueValidationError
		find_invoice.return_value = self._invoice()

		idempotency.save_once(invoice, "checkout-abc12345")

		db.savepoint.assert_called_once()
		db.rollback.assert_called_once()
		self.assertEqual(
			db.rollback.call_args.kwargs["save_point"], db.savepoint.call_args.args[0]
		)

	@patch(f"{MODULE}.find_invoice", return_value=None)
	@patch(f"{MODULE}.frappe.db")
	def test_a_duplicate_on_something_else_is_not_swallowed(self, db, _find):
		# Nothing carries our key, so the clash was another unique column.
		invoice = self._invoice()
		invoice.save.side_effect = frappe.DuplicateEntryError

		with self.assertRaises(frappe.DuplicateEntryError):
			idempotency.save_once(invoice, "checkout-abc12345")

	@patch(f"{MODULE}.frappe.db")
	def test_without_a_key_nothing_changes(self, db):
		invoice = self._invoice()

		saved, replayed = idempotency.save_once(invoice, None)

		invoice.save.assert_called_once_with(ignore_permissions=True)
		db.savepoint.assert_not_called()
		self.assertFalse(replayed)


class TestUnmigratedSite(FrappeTestCase):
	"""The column ships as a fixture; a site without it must still take orders."""

	@patch(f"{MODULE}.supported", return_value=False)
	def test_lookup_is_skipped(self, _supported):
		self.assertIsNone(idempotency.find_invoice("checkout-abc12345"))

	@patch(f"{MODULE}.supported", return_value=False)
	def test_stamping_is_skipped(self, _supported):
		invoice = MagicMock()
		idempotency.stamp(invoice, "checkout-abc12345")
		invoice.set.assert_not_called()

	@patch(f"{MODULE}.frappe.db")
	@patch(f"{MODULE}.supported", return_value=False)
	def test_saving_still_works(self, _supported, db):
		invoice = MagicMock()
		idempotency.save_once(invoice, "checkout-abc12345")
		invoice.save.assert_called_once_with(ignore_permissions=True)
		db.savepoint.assert_not_called()


class TestFieldIsInstalled(FrappeTestCase):
	def test_the_column_exists_and_is_unique(self):
		"""Without the unique index the whole guarantee is just a lookup."""
		meta = frappe.get_meta("Sales Invoice")
		field = meta.get_field(idempotency.IDEMPOTENCY_FIELD)
		self.assertIsNotNone(field, "custom_idempotency_key is missing -- run bench migrate")
		self.assertTrue(field.unique, "custom_idempotency_key must be unique")
