# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.sales_invoice.item_row import (
    build_invoice_item_row,
    get_allowed_custom_item_fields,
)


def _meta(fields):
    return frappe._dict(fields=[frappe._dict(f) for f in fields])


class TestInvoiceItemRow(FrappeTestCase):
    def test_gift_card_fields_are_allowed(self):
        allowed = get_allowed_custom_item_fields()
        for fieldname in (
            "custom_is_gift_card_item",
            "custom_gift_card_type",
            "custom_gift_card_code",
            "custom_gift_amount",
            "custom_coupon_value",
            "custom_choose_qty",
        ):
            self.assertIn(fieldname, allowed)

    def test_core_accounting_fields_are_not_allowed(self):
        allowed = get_allowed_custom_item_fields()
        for fieldname in ("income_account", "cost_center", "price_list_rate", "discount_percentage"):
            self.assertNotIn(fieldname, allowed)

    def test_layout_and_attachment_fields_are_skipped(self):
        meta = _meta(
            [
                {"fieldname": "custom_gift_card", "fieldtype": "Section Break", "is_custom_field": 1},
                {"fieldname": "custom_column_break_ppfaw", "fieldtype": "Column Break", "is_custom_field": 1},
                {"fieldname": "custom_gift_receipt", "fieldtype": "Attach", "is_custom_field": 1},
                {"fieldname": "custom_gift_amount", "fieldtype": "Data", "is_custom_field": 1},
            ]
        )
        with patch("excel_restaurant_pos.shared.sales_invoice.item_row.frappe.get_meta", return_value=meta):
            self.assertEqual(get_allowed_custom_item_fields(), ("custom_gift_amount",))

    def test_row_carries_custom_fields_added_later(self):
        """A custom field the endpoint never heard of still reaches the row."""
        meta = _meta([{"fieldname": "custom_brand_new_gift_field", "fieldtype": "Data", "is_custom_field": 1}])
        with patch("excel_restaurant_pos.shared.sales_invoice.item_row.frappe.get_meta", return_value=meta):
            row = build_invoice_item_row(
                {"item_code": "GIFT-50", "qty": "2", "rate": "50", "custom_brand_new_gift_field": "x"}
            )

        self.assertEqual(row["item_code"], "GIFT-50")
        self.assertEqual(row["qty"], 2.0)
        self.assertEqual(row["rate"], 50.0)
        self.assertEqual(row["custom_brand_new_gift_field"], "x")

    def test_unsent_fields_are_omitted_so_defaults_apply(self):
        meta = _meta([{"fieldname": "custom_if_not_available", "fieldtype": "Select", "is_custom_field": 1}])
        with patch("excel_restaurant_pos.shared.sales_invoice.item_row.frappe.get_meta", return_value=meta):
            row = build_invoice_item_row({"item_code": "COKE"})

        self.assertNotIn("custom_if_not_available", row)

    def test_non_custom_payload_keys_are_dropped(self):
        meta = _meta([{"fieldname": "custom_gift_amount", "fieldtype": "Data", "is_custom_field": 1}])
        with patch("excel_restaurant_pos.shared.sales_invoice.item_row.frappe.get_meta", return_value=meta):
            row = build_invoice_item_row({"item_code": "GIFT-50", "income_account": "Hacked - X"})

        self.assertNotIn("income_account", row)

    def test_gift_card_line_round_trip(self):
        row = build_invoice_item_row(
            {
                "item_code": "GIFT-CARD",
                "qty": 1,
                "rate": 5000,
                "custom_is_gift_card_item": 1,
                "custom_gift_card_type": "Existing",
                "custom_gift_card_code": "GIFT0001",
                "custom_gift_amount": 5000,
                "custom_coupon_value": 5000,
            }
        )

        self.assertEqual(row["custom_is_gift_card_item"], 1)
        self.assertEqual(row["custom_gift_card_type"], "Existing")
        self.assertEqual(row["custom_gift_card_code"], "GIFT0001")
        self.assertEqual(row["custom_gift_amount"], 5000)
        self.assertEqual(row["custom_coupon_value"], 5000)
