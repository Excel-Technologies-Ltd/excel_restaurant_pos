# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.print_format.invoice_pdf import (
	FALLBACK_PRINT_FORMAT,
	build_pdf_response,
	is_delivery_order,
	pdf_filename,
	render_pdf,
	resolve_print_format,
)

MODULE = "excel_restaurant_pos.shared.print_format.invoice_pdf"


def reset_pdf_rate_limit():
	"""Clear the per caller render counter.

	It lives in redis for the whole window, so without this the burst test
	spends the budget for every test after it -- and for the next run of the
	suite, which starts inside the same window.
	"""
	frappe.cache().delete_value(f"arcpos:rate:invoice_pdf:user:{frappe.session.user}")


def _invoice(service_type="Pickup", name="ORD-26-01409", docstatus=1):
	return frappe._dict(
		name=name,
		custom_service_type=service_type,
		docstatus=docstatus,
	)


class TestPrintFormatSelection(FrappeTestCase):
	"""The format comes from ArcPOS Settings, never from the caller."""

	def test_delivery_is_detected_case_insensitively(self):
		self.assertTrue(is_delivery_order(_invoice("Delivery")))
		self.assertTrue(is_delivery_order(_invoice(" delivery ")))
		self.assertFalse(is_delivery_order(_invoice("Pickup")))
		self.assertFalse(is_delivery_order(_invoice(None)))

	@patch(f"{MODULE}.frappe.db.exists", return_value=True)
	@patch(f"{MODULE}.frappe.db.get_single_value")
	def test_delivery_uses_the_delivery_format(self, get_single_value, _exists):
		get_single_value.return_value = "ArcPOS Delivery Slip"

		self.assertEqual(resolve_print_format(_invoice("Delivery")), "ArcPOS Delivery Slip")
		get_single_value.assert_called_once_with("ArcPOS Settings", "default_delivery_pf")

	@patch(f"{MODULE}.frappe.db.exists", return_value=True)
	@patch(f"{MODULE}.frappe.db.get_single_value")
	def test_everything_else_uses_the_default_format(self, get_single_value, _exists):
		get_single_value.return_value = "ArcPOS Receipt"

		for service_type in ("Pickup", "Dine-in", "Takeout"):
			get_single_value.reset_mock()

			self.assertEqual(resolve_print_format(_invoice(service_type)), "ArcPOS Receipt")
			get_single_value.assert_called_once_with("ArcPOS Settings", "print_format_for_order")

	@patch(f"{MODULE}.frappe.db.get_single_value", return_value="")
	def test_an_unset_setting_falls_back_rather_than_failing(self, _get_single_value):
		# A customer downloading their own receipt should not be blocked by a
		# setting nobody filled in.
		self.assertEqual(resolve_print_format(_invoice("Delivery")), FALLBACK_PRINT_FORMAT)

	@patch(f"{MODULE}.frappe.log_error")
	@patch(f"{MODULE}.frappe.db.exists", return_value=False)
	@patch(f"{MODULE}.frappe.db.get_single_value", return_value="Deleted Format")
	def test_a_format_that_no_longer_exists_falls_back_and_is_logged(
		self, _get_single_value, _exists, log_error
	):
		# The setting is a Link, but a format can be renamed or deleted after it
		# was chosen; rendering would otherwise die in the template.
		self.assertEqual(resolve_print_format(_invoice()), FALLBACK_PRINT_FORMAT)
		log_error.assert_called_once()


class TestRenderFailure(FrappeTestCase):
	@patch(f"{MODULE}.frappe.log_error")
	@patch(f"{MODULE}.frappe.get_print", side_effect=OSError("wkhtmltopdf reported an error"))
	def test_a_render_failure_becomes_a_readable_error(self, _get_print, log_error):
		# wkhtmltopdf's stderr names the site host and means nothing to a
		# customer, so it is translated and kept in the log instead.
		with self.assertRaises(frappe.ValidationError) as raised:
			render_pdf(_invoice(), "ArcPOS Receipt")

		self.assertIn("ORD-26-01409", str(raised.exception))
		self.assertNotIn("wkhtmltopdf", str(raised.exception))
		log_error.assert_called_once()


class TestPdfResponse(FrappeTestCase):
	def setUp(self):
		reset_pdf_rate_limit()

	def test_filename_is_the_order_number(self):
		self.assertEqual(pdf_filename(_invoice()), "ORD-26-01409.pdf")

	@patch(f"{MODULE}.render_pdf", return_value=b"%PDF-1.4 fake")
	@patch(f"{MODULE}.resolve_print_format", return_value="ArcPOS Receipt")
	@patch(f"{MODULE}.get_invoice")
	def test_response_is_a_pdf_attachment(self, get_invoice, _format, _render):
		get_invoice.return_value = _invoice()

		response = build_pdf_response("ORD-26-01409")

		self.assertEqual(response.mimetype, "application/pdf")
		self.assertIn("attachment", response.headers["Content-Disposition"])
		self.assertIn("ORD-26-01409.pdf", response.headers["Content-Disposition"])
		self.assertEqual(response.headers["X-Print-Format"], "ArcPOS Receipt")
		self.assertEqual(response.headers["Content-Length"], str(len(b"%PDF-1.4 fake")))

	@patch(f"{MODULE}.render_pdf", return_value=b"%PDF-1.4 fake")
	@patch(f"{MODULE}.resolve_print_format", return_value="ArcPOS Receipt")
	@patch(f"{MODULE}.get_invoice")
	def test_a_receipt_is_never_cached_and_readable_cross_origin(
		self, get_invoice, _format, _render
	):
		# It carries the customer's name, address and phone.
		get_invoice.return_value = _invoice()

		response = build_pdf_response("ORD-26-01409")

		self.assertIn("no-store", response.headers["Cache-Control"])
		self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
		self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
		self.assertIn("Content-Disposition", response.headers["Access-Control-Expose-Headers"])
		self.assertIn("X-Print-Format", response.headers["Access-Control-Expose-Headers"])

	# A burst has to be refused: the route is guest reachable and every render
	# is real CPU.
	@patch(f"{MODULE}.render_pdf", return_value=b"%PDF")
	@patch(f"{MODULE}.resolve_print_format", return_value="ArcPOS Receipt")
	@patch(f"{MODULE}.get_invoice")
	def test_rate_limit_blocks_a_burst(self, get_invoice, _format, _render):
		get_invoice.return_value = _invoice()
		outcomes = []

		for _attempt in range(35):
			try:
				build_pdf_response("ORD-26-01409")
				outcomes.append("ok")
			except frappe.ValidationError:
				outcomes.append("throttled")

		self.assertIn("throttled", outcomes)
		self.assertEqual(outcomes.count("ok"), 30)


class TestInvoiceLookup(FrappeTestCase):
	def test_a_missing_name_is_rejected(self):
		with self.assertRaises(frappe.MandatoryError):
			from excel_restaurant_pos.shared.print_format.invoice_pdf import get_invoice

			get_invoice("")

	@patch(f"{MODULE}.frappe.db.exists", return_value=False)
	def test_an_unknown_invoice_is_rejected(self, _exists):
		from excel_restaurant_pos.shared.print_format.invoice_pdf import get_invoice

		with self.assertRaises(frappe.DoesNotExistError):
			get_invoice("ORD-NOPE")

	@patch(f"{MODULE}.frappe.get_doc")
	@patch(f"{MODULE}.frappe.db.exists", return_value=True)
	def test_a_cancelled_order_is_rejected(self, _exists, get_doc):
		from excel_restaurant_pos.shared.print_format.invoice_pdf import get_invoice

		get_doc.return_value = _invoice(docstatus=2)

		with self.assertRaises(frappe.ValidationError):
			get_invoice("ORD-26-01409")
