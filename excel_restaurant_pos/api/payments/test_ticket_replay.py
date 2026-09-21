# Copyright (c) 2026, Excel and Contributors
# See license.txt

import importlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.payments.helper.claim_ticket import claim_ticket

# The package __init__ re-exports the function under the module's name.
module = importlib.import_module("excel_restaurant_pos.api.payments.receipt_payment")
MODULE = "excel_restaurant_pos.api.payments.receipt_payment"

INVOICE = "WEB-26-99901"
APPROVED = {"success": "true", "receipt": {"result": "a"}, "request": {"order_no": INVOICE}}


def _make_ticket(ticket="TKT-REPLAY-1", redeemed=False):
	doc = frappe.get_doc(
		{"doctype": "Payment Ticket", "ticket": ticket, "invoice_no": INVOICE}
	).insert(ignore_permissions=True, ignore_links=True)
	if redeemed:
		frappe.db.set_value("Payment Ticket", doc.name, "redeemed_at", frappe.utils.now_datetime())
	return doc.name


class TestClaimTicket(FrappeTestCase):
	"""A Moneris receipt keeps answering "approved" forever, so the ticket has to
	remember that it was spent."""

	def test_the_first_claim_wins(self):
		name = _make_ticket()
		self.assertTrue(claim_ticket(name, via="receipt_payment"))

	def test_a_second_claim_loses(self):
		name = _make_ticket()
		claim_ticket(name, via="receipt_payment")
		self.assertFalse(claim_ticket(name, via="scheduler"))

	def test_the_claim_records_who_made_it(self):
		name = _make_ticket()
		claim_ticket(name, via="scheduler")
		row = frappe.db.get_value("Payment Ticket", name, ["redeemed_at", "redeemed_via"], as_dict=True)
		self.assertIsNotNone(row.redeemed_at)
		self.assertEqual(row.redeemed_via, "scheduler")


class TestReceiptPaymentReplay(FrappeTestCase):
	def _call(self, ticket="TKT-REPLAY-1", order_no=INVOICE, receipt=APPROVED):
		frappe.local.form_dict = frappe._dict(
			ticket=ticket,
			order_no=order_no,
			payments=[{"mode_of_payment": "Card", "amount": 10}],
		)
		invoice = MagicMock()
		invoice.name = INVOICE
		with patch(f"{MODULE}.check_receipt", return_value=receipt) as gateway, patch(
			f"{MODULE}.frappe.get_doc", return_value=invoice
		), patch(f"{MODULE}.create_payment_entry") as create_pe:
			result = module.receipt_payment()
		return result, gateway, create_pe

	def test_a_fresh_ticket_is_paid_once(self):
		name = _make_ticket()

		result, _gateway, create_pe = self._call()

		self.assertEqual(result, {"success": True})
		create_pe.assert_called_once()
		self.assertIsNotNone(frappe.db.get_value("Payment Ticket", name, "redeemed_at"))

	def test_replaying_a_spent_ticket_makes_no_payment_entry(self):
		"""The bug: one real payment, as many Payment Entries as were requested."""
		_make_ticket()
		self._call()

		for _ in range(3):
			result, _gateway, create_pe = self._call()
			self.assertEqual(result, {"success": True, "already_processed": True})
			create_pe.assert_not_called()

	def test_a_spent_ticket_is_answered_without_asking_moneris(self):
		# Moneris would say "approved" -- asking changes nothing but the latency.
		_make_ticket(redeemed=True)

		_result, gateway, _create_pe = self._call()

		gateway.assert_not_called()

	def test_a_replay_with_the_wrong_order_is_still_refused(self):
		_make_ticket(redeemed=True)

		with self.assertRaises(frappe.ValidationError):
			self._call(order_no="WEB-26-00000")

	def test_losing_the_claim_race_makes_no_payment_entry(self):
		# Another request claimed the ticket between our read and our claim.
		_make_ticket()
		with patch(f"{MODULE}.claim_ticket", return_value=False):
			result, _gateway, create_pe = self._call()

		self.assertEqual(result, {"success": True, "already_processed": True})
		create_pe.assert_not_called()

	def test_a_declined_receipt_does_not_burn_the_ticket(self):
		name = _make_ticket()

		with self.assertRaises(frappe.ValidationError):
			self._call(receipt={"success": "true", "receipt": {"result": "d"}})

		self.assertIsNone(frappe.db.get_value("Payment Ticket", name, "redeemed_at"))


class TestSchedulerUsesTheClaim(FrappeTestCase):
	def test_the_sweep_claims_before_paying(self):
		import inspect

		from excel_restaurant_pos.utils import scheduled_tasks

		source = inspect.getsource(scheduled_tasks.delete_stale_website_orders)
		claim = source.index('claim_ticket(payment_ticket.name, via="scheduler")')
		pay = source.index("create_payment_entry(**args)")
		self.assertLess(claim, pay)
		self.assertIn("rollback(save_point=STALE_ORDER_SAVEPOINT)", source)
