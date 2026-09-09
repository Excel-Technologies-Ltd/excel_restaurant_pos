# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.sales_invoice.handlers.update_sales_invoice import (
	_apply_docstatus,
	_keep_due_date_valid,
)

MODULE = "excel_restaurant_pos.api.sales_invoice.handlers.update_sales_invoice"


def _invoice(docstatus=0, name="WEB-26-02020"):
	invoice = MagicMock()
	invoice.name = name
	invoice.docstatus = docstatus
	invoice.flags = frappe._dict()
	return invoice


class TestApplyDocstatus(FrappeTestCase):
	"""`docstatus` was dropped on the update path, so submits did nothing."""

	def test_docstatus_1_submits_a_draft(self):
		invoice = _invoice(docstatus=0)

		_apply_docstatus(invoice, 1)

		invoice.submit.assert_called_once()
		self.assertIs(invoice.flags.ignore_permissions, True)

	def test_a_string_from_the_request_still_submits(self):
		# form_dict values arrive as strings.
		invoice = _invoice(docstatus=0)

		_apply_docstatus(invoice, "1")

		invoice.submit.assert_called_once()

	def test_omitting_docstatus_leaves_the_draft_alone(self):
		for value in (None, ""):
			invoice = _invoice(docstatus=0)

			_apply_docstatus(invoice, value)

			invoice.submit.assert_not_called()

	def test_docstatus_0_is_a_no_op(self):
		invoice = _invoice(docstatus=0)

		_apply_docstatus(invoice, 0)

		invoice.submit.assert_not_called()

	def test_resubmitting_is_not_an_error(self):
		# The storefront may retry; asking for a state it is already in is fine.
		invoice = _invoice(docstatus=1)

		_apply_docstatus(invoice, 1)

		invoice.submit.assert_not_called()

	def test_a_cancelled_order_cannot_be_submitted(self):
		invoice = _invoice(docstatus=2)

		with self.assertRaises(frappe.ValidationError):
			_apply_docstatus(invoice, 1)

		invoice.submit.assert_not_called()

	def test_cancelling_is_not_offered_here(self):
		# This route is guest reachable and a cancel reverses posted ledger
		# entries, which should not happen by passing a number to an order API.
		invoice = _invoice(docstatus=1)

		with self.assertRaises(frappe.ValidationError) as raised:
			_apply_docstatus(invoice, 2)

		self.assertIn("not supported", str(raised.exception))
		invoice.cancel.assert_not_called()


class TestKeepDueDateValid(FrappeTestCase):
	"""A draft left overnight fails ERPNext's own due date rule.

	With set_posting_time unchecked, posting_date moves to today on every save
	while due_date keeps the day the order was taken -- so submitting a stale
	draft died on "Due Date cannot be before Posting / Supplier Invoice Date".
	"""

	def _invoice(self, due_date, posting_date="2026-07-23", schedule=None, set_posting_time=0):
		invoice = MagicMock()
		invoice.due_date = due_date
		invoice.posting_date = posting_date
		rows = [frappe._dict(due_date=d) for d in (schedule or [])]
		invoice.get.side_effect = lambda field, default=None: {
			"payment_schedule": rows,
			"set_posting_time": set_posting_time,
		}.get(field, default)
		return invoice, rows

	@patch(f"{MODULE}.nowdate", return_value="2026-09-09")
	def test_a_stale_due_date_is_pushed_to_today(self, _nowdate):
		invoice, _rows = self._invoice(due_date="2026-07-23")

		_keep_due_date_valid(invoice)

		self.assertEqual(str(invoice.due_date), "2026-09-09")

	@patch(f"{MODULE}.nowdate", return_value="2026-09-09")
	def test_the_payment_schedule_moves_with_it(self, _nowdate):
		# ERPNext's set_due_date() rebuilds due_date from these rows on every
		# validate, so fixing the field alone is undone before it is checked.
		invoice, rows = self._invoice(due_date="2026-07-23", schedule=["2026-07-23"])

		_keep_due_date_valid(invoice)

		self.assertEqual(str(rows[0].due_date), "2026-09-09")

	@patch(f"{MODULE}.nowdate", return_value="2026-09-09")
	def test_a_real_future_due_date_is_kept(self, _nowdate):
		invoice, rows = self._invoice(due_date="2026-12-31", schedule=["2026-12-31"])

		_keep_due_date_valid(invoice)

		self.assertEqual(invoice.due_date, "2026-12-31")
		self.assertEqual(rows[0].due_date, "2026-12-31")

	@patch(f"{MODULE}.nowdate", return_value="2026-09-09")
	def test_a_missing_due_date_is_filled_in(self, _nowdate):
		invoice, _rows = self._invoice(due_date=None)

		_keep_due_date_valid(invoice)

		self.assertEqual(str(invoice.due_date), "2026-09-09")

	@patch(f"{MODULE}.nowdate", return_value="2026-09-09")
	def test_a_pinned_posting_date_is_respected(self, _nowdate):
		# set_posting_time = 1 means ERPNext will not move posting_date, so the
		# invoice's own date is what due_date has to clear.
		invoice, _rows = self._invoice(
			due_date="2026-07-01", posting_date="2026-07-23", set_posting_time=1
		)

		_keep_due_date_valid(invoice)

		self.assertEqual(str(invoice.due_date), "2026-07-23")
