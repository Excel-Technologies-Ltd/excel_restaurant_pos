# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.payments.helper.settle_zero_payment import (
	is_fully_discounted,
	settle_zero_payment,
)

MODULE = "excel_restaurant_pos.api.payments.helper.settle_zero_payment"
PREDICATE = "excel_restaurant_pos.doc_event.sales_invoice.validate_zero_value.zero_total_is_discount_backed"


def _invoice(grand_total=0.0, docstatus=0, name="SINV-WEB-1", status="Draft"):
	invoice = MagicMock()
	invoice.name = name
	invoice.grand_total = grand_total
	invoice.docstatus = docstatus
	invoice.flags = frappe._dict()
	invoice.get.side_effect = lambda field, default=None: {"status": status}.get(field, default)
	return invoice


class TestIsFullyDiscounted(FrappeTestCase):
	def test_zero_and_negative_need_no_payment(self):
		self.assertTrue(is_fully_discounted(_invoice(grand_total=0)))
		self.assertTrue(is_fully_discounted(_invoice(grand_total=-0.0)))

	def test_a_positive_total_still_needs_paying(self):
		self.assertFalse(is_fully_discounted(_invoice(grand_total=12.5)))


class TestSettleZeroPayment(FrappeTestCase):
	"""A gift card covering the whole basket must not reach the gateway.

	The gateway refuses a $0 transaction, which used to strand the order as a
	draft -- so `record_gift_card_redemptions` never ran and the customer's
	balance was never actually spent.
	"""

	@patch(f"{MODULE}._discard_payment_tickets")
	@patch(PREDICATE, return_value=True)
	def test_a_gift_card_backed_zero_is_submitted(self, _backed, _discard):
		invoice = _invoice()

		result = settle_zero_payment(invoice)

		invoice.submit.assert_called_once()
		self.assertIs(invoice.flags.ignore_permissions, True)
		self.assertFalse(result["payment_required"])
		self.assertTrue(result["paid"])
		self.assertEqual(result["invoice"], "SINV-WEB-1")

	@patch(f"{MODULE}._discard_payment_tickets")
	@patch(PREDICATE, return_value=True)
	def test_a_stale_ticket_is_discarded_before_submit(self, _backed, discard):
		# Left behind, it stays replayable through api.payments.receipt_payment,
		# which would try to submit the same invoice a second time.
		invoice = _invoice()

		settle_zero_payment(invoice)

		discard.assert_called_once_with("SINV-WEB-1")

	@patch(f"{MODULE}._discard_payment_tickets")
	@patch(PREDICATE, return_value=False)
	def test_a_zero_with_no_discount_behind_it_is_refused(self, _backed, _discard):
		# This route is guest reachable, so a free basket must not be able to
		# submit itself just by costing nothing.
		invoice = _invoice()

		with self.assertRaises(frappe.ValidationError):
			settle_zero_payment(invoice)

		invoice.submit.assert_not_called()

	@patch(f"{MODULE}._discard_payment_tickets")
	@patch(PREDICATE, return_value=True)
	def test_an_already_submitted_order_is_not_submitted_twice(self, _backed, _discard):
		# The storefront may retry; a double tap must read as success, not error.
		invoice = _invoice(docstatus=1, status="Paid")

		result = settle_zero_payment(invoice)

		invoice.submit.assert_not_called()
		self.assertTrue(result["paid"])
		self.assertEqual(result["status"], "Paid")

	@patch(f"{MODULE}._discard_payment_tickets")
	def test_a_cancelled_order_is_rejected(self, _discard):
		invoice = _invoice(docstatus=2)

		with self.assertRaises(frappe.ValidationError):
			settle_zero_payment(invoice)

		invoice.submit.assert_not_called()


class TestGetPaymentTicketSkipsGatewayAtZero(FrappeTestCase):
	@patch("excel_restaurant_pos.api.payments.get_payment_ticket._request_payment_ticket")
	@patch("excel_restaurant_pos.api.payments.get_payment_ticket._get_existing_ticket_if_valid")
	@patch("excel_restaurant_pos.api.payments.get_payment_ticket.settle_zero_payment")
	@patch("excel_restaurant_pos.api.payments.get_payment_ticket._get_invoice")
	@patch(
		"excel_restaurant_pos.api.payments.get_payment_ticket._validate_invoice_number",
		return_value="SINV-WEB-1",
	)
	def test_zero_total_never_reaches_the_gateway(
		self, _number, get_invoice, settle, existing_ticket, request_ticket
	):
		from excel_restaurant_pos.api.payments.get_payment_ticket import get_payment_ticket

		get_invoice.return_value = _invoice(grand_total=0)
		settle.return_value = {"payment_required": False}

		result = get_payment_ticket()

		settle.assert_called_once()
		request_ticket.assert_not_called()
		# Also never reuses a ticket minted while the order still had a balance:
		# applying the gift card is what emptied it.
		existing_ticket.assert_not_called()
		self.assertFalse(result["payment_required"])

	@patch("excel_restaurant_pos.api.payments.get_payment_ticket.save_ticket_to_db")
	@patch(
		"excel_restaurant_pos.api.payments.get_payment_ticket._request_payment_ticket",
		return_value="TKT-1",
	)
	@patch("excel_restaurant_pos.api.payments.get_payment_ticket._prepare_payment_payload", return_value={})
	@patch("excel_restaurant_pos.api.payments.get_payment_ticket.get_payment_config", return_value={})
	@patch(
		"excel_restaurant_pos.api.payments.get_payment_ticket._get_existing_ticket_if_valid",
		return_value=None,
	)
	@patch("excel_restaurant_pos.api.payments.get_payment_ticket.settle_zero_payment")
	@patch("excel_restaurant_pos.api.payments.get_payment_ticket._get_invoice")
	@patch(
		"excel_restaurant_pos.api.payments.get_payment_ticket._validate_invoice_number",
		return_value="SINV-WEB-2",
	)
	def test_a_payable_total_still_goes_to_the_gateway(
		self, _number, get_invoice, settle, _existing, _config, _payload, request_ticket, _save
	):
		from excel_restaurant_pos.api.payments.get_payment_ticket import get_payment_ticket

		get_invoice.return_value = _invoice(grand_total=25.0)

		result = get_payment_ticket()

		settle.assert_not_called()
		request_ticket.assert_called_once()
		self.assertEqual(result, {"ticket": "TKT-1"})
