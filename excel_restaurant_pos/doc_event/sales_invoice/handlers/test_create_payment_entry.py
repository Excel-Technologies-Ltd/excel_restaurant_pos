# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry import (
	create_payment_entry,
)

MODULE = "excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry"


def _invoice(payments=None, name="ORD-26-01318"):
	invoice = MagicMock()
	invoice.name = name
	invoice.company = "Bancan Kitchen POS"
	invoice.customer = "CUST-1"
	invoice.payments = payments if payments is not None else []
	invoice.get.side_effect = lambda field, default=None: {
		"custom_with_arcpos_payment": 1,
		"territory": "Eglinton Ave E",
	}.get(field, default)
	return invoice


class TestCreatePaymentEntryReportsDoingNothing(FrappeTestCase):
	"""Creating nothing used to look exactly like success.

	Enqueued from submit_sales_invoice, this returned having created no Payment
	Entry and the RQ job showed as finished -- so an order that was meant to be
	paid quietly never was, with nothing anywhere to say so.
	"""

	def setUp(self):
		for target in ("frappe.set_user", "get_receivable_account"):
			patcher = patch(
				f"{MODULE}.{target}",
				**({"return_value": "Debtors - BKP"} if "receivable" in target else {}),
			)
			patcher.start()
			self.addCleanup(patcher.stop)

	@patch(f"{MODULE}.frappe.log_error")
	@patch(f"{MODULE}.frappe.get_doc")
	def test_an_invoice_with_no_payment_rows_is_logged(self, get_doc, log_error):
		# Every invoice from api.sales_invoices.add lands here: _add_payments is
		# commented out, so nothing populates the table.
		get_doc.return_value = _invoice(payments=[])

		result = create_payment_entry("ORD-26-01318")

		self.assertIsNone(result)
		log_error.assert_called_once()
		self.assertIn("ORD-26-01318", log_error.call_args.args[0])

	@patch(f"{MODULE}.get_mode_of_payment_account", return_value="Cash - BKP")
	@patch(f"{MODULE}.frappe.log_error")
	@patch(f"{MODULE}.frappe.get_doc")
	def test_a_row_missing_its_amount_is_logged(self, get_doc, log_error, _account):
		get_doc.return_value = _invoice(payments=[{"mode_of_payment": "Cash", "amount": 0}])

		create_payment_entry("ORD-26-01318")

		# Once for the skipped row, once for having created nothing at all.
		self.assertEqual(log_error.call_count, 2)

	@patch(f"{MODULE}.get_mode_of_payment_account", return_value=None)
	@patch(f"{MODULE}.frappe.log_error")
	@patch(f"{MODULE}.frappe.get_doc")
	def test_a_mode_of_payment_without_an_account_is_logged(self, get_doc, log_error, _account):
		get_doc.return_value = _invoice(payments=[{"mode_of_payment": "Cash", "amount": 20.0}])

		create_payment_entry("ORD-26-01318")

		self.assertEqual(log_error.call_count, 2)
		self.assertIn("has no account", log_error.call_args_list[0].args[0])

	@patch(f"{MODULE}.fill_required_payment_entry_fields")
	@patch(f"{MODULE}.get_mode_of_payment_account", return_value="Cash - BKP")
	@patch(f"{MODULE}.frappe.log_error")
	@patch(f"{MODULE}.frappe.new_doc")
	@patch(f"{MODULE}.frappe.get_doc")
	def test_a_usable_row_still_creates_and_submits(
		self, get_doc, new_doc, log_error, _account, _fill
	):
		get_doc.return_value = _invoice(payments=[{"mode_of_payment": "Cash", "amount": 20.0}])
		entry = MagicMock()
		entry.name = "RV-2026-00001"
		new_doc.return_value = entry

		result = create_payment_entry("ORD-26-01318")

		entry.insert.assert_called_once_with(ignore_permissions=True)
		entry.submit.assert_called_once()
		self.assertEqual(result, ["RV-2026-00001"])
		log_error.assert_not_called()


class TestSubmitEnqueuesAfterCommit(FrappeTestCase):
	"""A worker reads on its own connection, so the invoice must be committed."""

	@patch("excel_restaurant_pos.doc_event.sales_invoice.submit_sales_invoice.frappe.enqueue")
	def test_every_submit_job_waits_for_the_commit(self, enqueue):
		from excel_restaurant_pos.doc_event.sales_invoice.submit_sales_invoice import (
			submit_sales_invoice,
		)

		doc = MagicMock()
		doc.name = "ORD-26-01318"
		doc.custom_with_arcpos_payment = 1
		doc.items = [frappe._dict(item_code="ITEM-1", qty=1)]
		doc.as_dict.return_value = {"name": "ORD-26-01318"}

		submit_sales_invoice(doc, "on_submit")

		self.assertEqual(enqueue.call_count, 3)
		for call in enqueue.call_args_list:
			self.assertIs(call.kwargs["enqueue_after_commit"], True)
