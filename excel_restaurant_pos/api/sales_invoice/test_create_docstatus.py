# Copyright (c) 2026, Excel and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.sales_invoice.add_or_update_invoice import (
    _set_optional_fields,
)


class TestPayAtRestaurantSubmitsOnCreate(FrappeTestCase):
    """Pay-at-restaurant orders are created with docstatus 1 and must submit.

    These pin a Frappe behaviour this code relies on, and which was once
    misread from a comment: a *new* document inserted with docstatus 1 runs a
    real submit. check_if_latest() calls check_docstatus_transition(0) when
    there is no previous version, which sets _action to "submit", so on_submit
    runs and the ledger is posted.
    """

    def test_a_requested_docstatus_is_applied(self):
        invoice = frappe.new_doc("Sales Invoice")

        _set_optional_fields(invoice, frappe._dict(docstatus=1))

        self.assertEqual(frappe.utils.cint(invoice.docstatus), 1)

    def test_the_other_optional_fields_still_apply(self):
        invoice = frappe.new_doc("Sales Invoice")

        _set_optional_fields(invoice, frappe._dict(customer_name="Walk In"))

        self.assertEqual(invoice.customer_name, "Walk In")

    def test_frappe_treats_a_new_submitted_document_as_a_submit(self):
        """The rule this relies on, checked without writing anything.

        A real insert cannot be cleaned up in a test here: customer_change_handler,
        on the invoice's on_change hook, commits mid-save, so the class rollback
        cannot undo it and the cancel afterwards deadlocks on Notification Log.
        Verified end to end separately: a docstatus 1 insert posted 2 GL entries.
        """
        invoice = frappe.new_doc("Sales Invoice")
        invoice.docstatus = 1

        # What check_if_latest() does for a document with no previous version.
        invoice.check_docstatus_transition(0)

        self.assertEqual(invoice._action, "submit")
