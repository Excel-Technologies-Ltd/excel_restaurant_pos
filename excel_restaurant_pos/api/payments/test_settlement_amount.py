# Copyright (c) 2026, Excel and Contributors
# See license.txt

import importlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.payments.helper.settlement import (
	MATCH,
	MISMATCH,
	UNKNOWN,
	charged_amount,
	settlement_payments,
	verify_charged_amount,
)

module = importlib.import_module("excel_restaurant_pos.api.payments.receipt_payment")
MODULE = "excel_restaurant_pos.api.payments.receipt_payment"
HELPER = "excel_restaurant_pos.api.payments.helper.settlement"
INVOICE = "WEB-26-99902"


def _receipt(cc_amount=None, txn_total=None):
	receipt = {"result": "a"}
	if cc_amount is not None:
		receipt["cc"] = {"amount": cc_amount}
	request = {"order_no": INVOICE}
	if txn_total is not None:
		request["txn_total"] = txn_total
	return {"success": "true", "receipt": receipt, "request": request}


def _invoice(grand_total):
	invoice = MagicMock()
	invoice.name = INVOICE
	invoice.grand_total = grand_total
	return invoice


class TestChargedAmount(FrappeTestCase):
	def test_the_card_charge_wins(self):
		self.assertEqual(charged_amount(_receipt(cc_amount="12.34", txn_total="99.00")), 12.34)

	def test_the_preload_total_is_the_fallback(self):
		self.assertEqual(charged_amount(_receipt(txn_total="12.34")), 12.34)

	def test_no_amount_at_all_is_none(self):
		self.assertIsNone(charged_amount(_receipt()))

	def test_junk_is_skipped_rather_than_crashing(self):
		self.assertEqual(charged_amount(_receipt(cc_amount="", txn_total="5.00")), 5.0)


class TestVerifyChargedAmount(FrappeTestCase):
	def setUp(self):
		patcher = patch(f"{HELPER}.frappe.log_error")
		self.log_error = patcher.start()
		self.addCleanup(patcher.stop)

	def test_a_matching_charge(self):
		self.assertEqual(verify_charged_amount(_receipt(cc_amount="12.34"), _invoice(12.34)), MATCH)

	def test_a_cent_of_formatting_is_not_fraud(self):
		self.assertEqual(verify_charged_amount(_receipt(cc_amount="12.34"), _invoice(12.345)), MATCH)

	def test_the_grown_cart(self):
		"""Preloaded at $1, cart grown to $201, $1 ticket paid."""
		verdict = verify_charged_amount(_receipt(cc_amount="1.00", txn_total="1.00"), _invoice(201.0))

		self.assertEqual(verdict, MISMATCH)
		self.assertIn("possible fraud", self.log_error.call_args.kwargs["title"])

	def test_an_unreadable_receipt_is_logged_not_refused(self):
		# Refusing on our own parsing uncertainty would fail real payments.
		self.assertEqual(verify_charged_amount(_receipt(), _invoice(12.34)), UNKNOWN)
		self.log_error.assert_called_once()


class TestSettlementPayments(FrappeTestCase):
	@patch(f"{HELPER}.website_mode_of_payment", return_value="Moneris Web")
	def test_the_amount_is_always_the_invoice_total(self, _mode):
		self.assertEqual(
			settlement_payments(_invoice(12.34), fallback_mode="Cash"),
			[{"mode_of_payment": "Moneris Web", "amount": 12.34}],
		)

	@patch(f"{HELPER}.frappe.log_error")
	@patch(f"{HELPER}.website_mode_of_payment", return_value=None)
	def test_the_request_mode_is_only_a_fallback(self, _mode, _log):
		self.assertEqual(settlement_payments(_invoice(5), fallback_mode="Card")[0]["mode_of_payment"], "Card")


class TestReceiptPaymentBooksTheRealAmount(FrappeTestCase):
	def _call(self, receipt, grand_total, claimed_amount):
		frappe.local.form_dict = frappe._dict(
			ticket="TKT-AMT-1",
			order_no=INVOICE,
			payments=[{"mode_of_payment": "Card", "amount": claimed_amount}],
		)
		ticket_row = frappe._dict(name="PT-AMT", invoice_no=INVOICE, redeemed_at=None)
		with patch(f"{MODULE}.get_ticket", return_value=ticket_row), patch(
			f"{MODULE}.check_receipt", return_value=receipt
		), patch(f"{MODULE}.frappe.get_doc", return_value=_invoice(grand_total)), patch(
			f"{MODULE}.claim_ticket", return_value=True
		) as claim, patch(f"{MODULE}.create_payment_entry") as create_pe, patch(
			"excel_restaurant_pos.api.payments.helper.settlement.frappe.log_error"
		):
			try:
				result = module.receipt_payment()
			except frappe.ValidationError:
				result = "refused"
		return result, claim, create_pe

	def test_an_inflated_request_amount_is_ignored(self):
		"""The request says $500; Moneris charged $12.34; so does the invoice."""
		result, _claim, create_pe = self._call(_receipt(cc_amount="12.34"), 12.34, claimed_amount=500)

		self.assertEqual(result, {"success": True})
		booked = create_pe.call_args.kwargs["payments"]
		self.assertEqual(booked[0]["amount"], 12.34)

	def test_the_grown_cart_is_refused_and_the_ticket_left_unspent(self):
		result, claim, create_pe = self._call(_receipt(cc_amount="1.00"), 201.0, claimed_amount=201)

		self.assertEqual(result, "refused")
		create_pe.assert_not_called()
		claim.assert_not_called()  # unspent, so staff can review it

	def test_the_request_no_longer_has_to_send_payments(self):
		frappe.local.form_dict = frappe._dict(ticket="TKT-AMT-1", order_no=INVOICE)
		ticket_row = frappe._dict(name="PT-AMT", invoice_no=INVOICE, redeemed_at=None)
		with patch(f"{MODULE}.get_ticket", return_value=ticket_row), patch(
			f"{MODULE}.check_receipt", return_value=_receipt(cc_amount="9.00")
		), patch(f"{MODULE}.frappe.get_doc", return_value=_invoice(9.0)), patch(
			f"{MODULE}.claim_ticket", return_value=True
		), patch(f"{MODULE}.create_payment_entry") as create_pe:
			self.assertEqual(module.receipt_payment(), {"success": True})
		create_pe.assert_called_once()
