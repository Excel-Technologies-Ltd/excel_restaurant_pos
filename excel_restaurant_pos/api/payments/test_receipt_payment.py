# Copyright (c) 2026, Excel and Contributors
# See license.txt

import importlib
import inspect
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

# The package __init__ re-exports the function under the module name, so it
# has to be imported by path rather than as an attribute.
module = importlib.import_module("excel_restaurant_pos.api.payments.receipt_payment")

MODULE = "excel_restaurant_pos.api.payments.receipt_payment"


class TestNoDevelopmentBypass(FrappeTestCase):
    """The payment check used to be skippable by one word in site_config.

    `environment == "development"` disabled it entirely, on a guest reachable
    endpoint -- and site_config carries a second key of the same name for the
    Moneris store, so the two were easy to confuse.
    """

    def test_the_bypass_is_gone_from_the_source(self):
        source = inspect.getsource(module.receipt_payment)
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        self.assertNotIn("is_development", code)
        self.assertNotIn('"development"', code)

    def _call_with(self, receipt):
        frappe.local.form_dict = frappe._dict(
            ticket="TKT-1", order_no="WEB-26-00001", payments=[{"mode_of_payment": "Card", "amount": 10}]
        )
        ticket_row = frappe._dict(name="PT-1", invoice_no="WEB-26-00001", redeemed_at=None)
        with patch(f"{MODULE}.get_ticket", return_value=ticket_row):
            with patch(f"{MODULE}.check_receipt", return_value=receipt):
                return module.receipt_payment()

    def test_an_unapproved_receipt_is_refused_even_on_a_development_site(self):
        with patch.dict(frappe.conf, {"environment": "development"}):
            with self.assertRaises(frappe.ValidationError):
                self._call_with({"success": "true", "receipt": {"result": "d"}})

    def test_an_unsuccessful_call_is_refused_even_on_a_development_site(self):
        with patch.dict(frappe.conf, {"environment": "development"}):
            with self.assertRaises(frappe.ValidationError):
                self._call_with({"success": "false", "receipt": {"result": "a"}})

    def test_an_empty_receipt_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self._call_with({})


class TestQaAcceptsDeclined(FrappeTestCase):
    """arcpos_moneris_qa_accept_declined: QA store only, switch required."""

    def setUp(self):
        patcher = patch(f"{MODULE}.frappe.log_error")
        self.log_error = patcher.start()
        self.addCleanup(patcher.stop)

    def accepts(self, switch, environment, success="true"):
        with patch.dict(frappe.conf, {module.QA_ACCEPT_DECLINED_KEY: switch}), \
             patch(f"{MODULE}.get_payment_config", return_value={"environment": environment}):
            return module._qa_accepts_declined(success)

    def test_qa_with_the_switch_on_accepts(self):
        self.assertTrue(self.accepts(1, "qa"))

    def test_off_by_default(self):
        self.assertFalse(self.accepts(0, "qa"))

    def test_never_for_the_production_store(self):
        self.assertFalse(self.accepts(1, "prod"))
        self.assertFalse(self.accepts(1, ""))

    def test_never_for_a_ticket_moneris_did_not_answer_for(self):
        self.assertFalse(self.accepts(1, "qa", success="false"))

    def test_a_declined_receipt_goes_on_to_the_order_checks(self):
        """Accepted past the decline, then refused by the order-number check."""
        frappe.local.form_dict = frappe._dict(ticket="TKT-1", order_no="WEB-26-00001")
        ticket_row = frappe._dict(name="PT-1", invoice_no="WEB-26-00001", redeemed_at=None)
        receipt = {"success": "true", "receipt": {"result": "d"}, "request": {"order_no": "SOMETHING-ELSE"}}
        with patch.dict(frappe.conf, {module.QA_ACCEPT_DECLINED_KEY: 1}), \
             patch(f"{MODULE}.get_payment_config", return_value={"environment": "qa"}), \
             patch(f"{MODULE}.get_ticket", return_value=ticket_row), \
             patch(f"{MODULE}.check_receipt", return_value=receipt):
            with self.assertRaises(frappe.ValidationError) as refused:
                module.receipt_payment()
        self.assertIn("Order number mismatch", str(refused.exception))
        self.assertEqual(self.log_error.call_args.kwargs["title"], "Moneris QA: declined payment accepted")
