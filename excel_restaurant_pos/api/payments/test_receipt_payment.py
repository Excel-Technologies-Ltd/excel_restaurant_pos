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
        with patch(f"{MODULE}.frappe.db.get_value", return_value="WEB-26-00001"):
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
