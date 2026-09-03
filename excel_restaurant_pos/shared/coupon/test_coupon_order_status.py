# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.coupon.order_status import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_SUBMITTED,
    apply_coupon_order_status,
    on_cancel_sales_invoice_coupon_status,
    on_submit_sales_invoice_coupon_status,
    sync_coupon_order_status,
)
from excel_restaurant_pos.shared.coupon.services import COUPON_STATUS_REJECTED

MODULE = "excel_restaurant_pos.shared.coupon.order_status"


def _current(order_status=0, status="Active"):
    return frappe._dict(custom_order_status=order_status, custom_status=status)


class TestApplyCouponOrderStatus(FrappeTestCase):
    def test_submit_sets_order_status_only(self):
        with patch(f"{MODULE}.frappe.db.get_value", return_value=_current()):
            with patch(f"{MODULE}.frappe.db.set_value") as set_value:
                changed = apply_coupon_order_status("COUPON1", ORDER_STATUS_SUBMITTED)

        self.assertTrue(changed)
        self.assertEqual(set_value.call_args.args[2], {"custom_order_status": 1})

    def test_cancel_sets_order_status_and_rejects(self):
        with patch(f"{MODULE}.frappe.db.get_value", return_value=_current(order_status=1)):
            with patch(f"{MODULE}.frappe.db.set_value") as set_value:
                changed = apply_coupon_order_status("COUPON1", ORDER_STATUS_CANCELLED, reject=True)

        self.assertTrue(changed)
        self.assertEqual(
            set_value.call_args.args[2],
            {"custom_order_status": 2, "custom_status": COUPON_STATUS_REJECTED},
        )

    def test_already_correct_coupon_is_not_written(self):
        with patch(f"{MODULE}.frappe.db.get_value", return_value=_current(order_status=1)):
            with patch(f"{MODULE}.frappe.db.set_value") as set_value:
                changed = apply_coupon_order_status("COUPON1", ORDER_STATUS_SUBMITTED)

        self.assertFalse(changed)
        set_value.assert_not_called()

    def test_already_rejected_coupon_keeps_its_status(self):
        current = _current(order_status=1, status=COUPON_STATUS_REJECTED)
        with patch(f"{MODULE}.frappe.db.get_value", return_value=current):
            with patch(f"{MODULE}.frappe.db.set_value") as set_value:
                apply_coupon_order_status("COUPON1", ORDER_STATUS_CANCELLED, reject=True)

        self.assertEqual(set_value.call_args.args[2], {"custom_order_status": 2})

    def test_missing_coupon_is_skipped(self):
        with patch(f"{MODULE}.frappe.db.get_value", return_value=None):
            with patch(f"{MODULE}.frappe.db.set_value") as set_value:
                self.assertFalse(apply_coupon_order_status("GONE", ORDER_STATUS_SUBMITTED))

        set_value.assert_not_called()

    def test_null_order_status_is_treated_as_zero(self):
        with patch(f"{MODULE}.frappe.db.get_value", return_value=_current(order_status=None)):
            with patch(f"{MODULE}.frappe.db.set_value") as set_value:
                self.assertTrue(apply_coupon_order_status("COUPON1", ORDER_STATUS_SUBMITTED))

        self.assertEqual(set_value.call_args.args[2], {"custom_order_status": 1})


class TestSyncFromInvoice(FrappeTestCase):
    def test_every_coupon_on_the_order_is_updated(self):
        invoice = frappe._dict(name="ACC-SINV-2026-00001")

        with patch(f"{MODULE}.frappe.get_all", return_value=["C1", "C2"]):
            with patch(f"{MODULE}.apply_coupon_order_status", return_value=True) as apply_status:
                updated = sync_coupon_order_status(invoice, ORDER_STATUS_SUBMITTED)

        self.assertEqual(updated, 2)
        self.assertEqual(apply_status.call_count, 2)

    def test_invoice_with_no_coupons_is_a_no_op(self):
        with patch(f"{MODULE}.frappe.get_all", return_value=[]):
            with patch(f"{MODULE}.apply_coupon_order_status") as apply_status:
                self.assertEqual(sync_coupon_order_status("ACC-SINV-2026-00002", 1), 0)

        apply_status.assert_not_called()

    def test_submit_hook_passes_submitted_without_rejecting(self):
        with patch(f"{MODULE}.sync_coupon_order_status") as sync:
            on_submit_sales_invoice_coupon_status(frappe._dict(name="INV"))

        sync.assert_called_once_with(frappe._dict(name="INV"), ORDER_STATUS_SUBMITTED)

    def test_cancel_hook_rejects(self):
        with patch(f"{MODULE}.sync_coupon_order_status") as sync:
            on_cancel_sales_invoice_coupon_status(frappe._dict(name="INV"))

        self.assertEqual(sync.call_args.args[1], ORDER_STATUS_CANCELLED)
        self.assertTrue(sync.call_args.kwargs["reject"])


class TestHookRegistration(FrappeTestCase):
    def test_sales_invoice_hooks_are_registered(self):
        from excel_restaurant_pos.doc_event import custom_doc_events

        events = custom_doc_events["Sales Invoice"]
        self.assertIn(
            f"{MODULE}.on_submit_sales_invoice_coupon_status", events["on_submit"]
        )
        self.assertIn(
            f"{MODULE}.on_cancel_sales_invoice_coupon_status", events["on_cancel"]
        )

    def test_status_sync_runs_after_the_link_is_written(self):
        """finalize_auto_generated_coupon sets custom_generated_on_order on submit."""
        from excel_restaurant_pos.doc_event import custom_doc_events

        on_submit = custom_doc_events["Sales Invoice"]["on_submit"]
        self.assertLess(
            on_submit.index(
                "excel_restaurant_pos.shared.coupon.services.on_submit_sales_invoice_coupon"
            ),
            on_submit.index(f"{MODULE}.on_submit_sales_invoice_coupon_status"),
        )
