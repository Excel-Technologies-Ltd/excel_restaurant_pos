# Copyright (c) 2026, Excel and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.sales_invoice.add_or_update_invoice import (
    _set_optional_fields,
)


class TestDocstatusIsNotWrittenBeforeInsert(FrappeTestCase):
    """A document born submitted never runs on_submit.

    Frappe only treats a docstatus change as a submit when there is a previous
    version to compare against -- "previous is None for new document insert"
    (frappe/model/document.py). Writing docstatus=1 before the insert therefore
    produced an invoice that showed as submitted while posting no GL entries,
    redeeming no gift cards and queueing no payment entry.
    """

    def test_a_requested_docstatus_is_not_applied_to_a_new_invoice(self):
        invoice = frappe.new_doc("Sales Invoice")
        data = frappe._dict(docstatus=1, customer_name="Walk In")

        _set_optional_fields(invoice, data)

        self.assertEqual(
            frappe.utils.cint(invoice.docstatus),
            0,
            "docstatus must stay draft here; submitting is _apply_docstatus's job",
        )

    def test_the_other_optional_fields_still_apply(self):
        invoice = frappe.new_doc("Sales Invoice")

        _set_optional_fields(invoice, frappe._dict(customer_name="Walk In", discount_amount=5))

        self.assertEqual(invoice.customer_name, "Walk In")

    def test_the_create_path_submits_through_apply_docstatus(self):
        """Pay-at-restaurant still submits -- just through the correct route."""
        import importlib
        import inspect

        # The package __init__ re-exports the function under the module name.
        module = importlib.import_module(
            "excel_restaurant_pos.api.sales_invoice.add_or_update_invoice"
        )

        source = inspect.getsource(module.add_or_update_invoice)
        self.assertIn("_apply_docstatus(sales_invoice, data.get(\"docstatus\"))", source)
