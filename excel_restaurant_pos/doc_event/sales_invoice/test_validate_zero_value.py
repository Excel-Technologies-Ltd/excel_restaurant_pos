# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.doc_event.sales_invoice.validate_zero_value import (
    validate_non_zero_grand_total,
)

_MODULE = "excel_restaurant_pos.doc_event.sales_invoice.validate_zero_value"


class _Doc:
    def __init__(self, **kw):
        self._d = kw

    def get(self, key, default=None):
        return self._d.get(key, default)


class TestValidateZeroValue(FrappeTestCase):
    def test_positive_grand_total_always_passes(self):
        # No coupon needed when the total is positive.
        validate_non_zero_grand_total(_Doc(grand_total=10, total=10, discount_amount=0))

    def test_zero_without_coupon_is_rejected(self):
        with patch(f"{_MODULE}.resolve_applied_coupon_code", return_value=""):
            # zero via manual discount
            with self.assertRaises(frappe.ValidationError):
                validate_non_zero_grand_total(_Doc(grand_total=0, total=10, discount_amount=10))
            # zero via free / zero-priced items
            with self.assertRaises(frappe.ValidationError):
                validate_non_zero_grand_total(_Doc(grand_total=0, total=0, discount_amount=0))

    def test_negative_grand_total_without_coupon_is_rejected(self):
        with patch(f"{_MODULE}.resolve_applied_coupon_code", return_value=""):
            with self.assertRaises(frappe.ValidationError):
                validate_non_zero_grand_total(_Doc(grand_total=-5, total=10, discount_amount=15))

    def test_coupon_reducing_positive_subtotal_to_zero_is_allowed(self):
        with patch(f"{_MODULE}.resolve_applied_coupon_code", return_value="SAVE10"):
            # coupon covered a positive subtotal -> allowed
            validate_non_zero_grand_total(_Doc(grand_total=0, total=10, discount_amount=10))

    def test_gift_cards_reducing_positive_subtotal_to_zero_is_allowed(self):
        with patch(f"{_MODULE}.resolve_applied_coupon_code", return_value=""):
            with patch(f"{_MODULE}.invoice_has_applied_gift_cards", return_value=True):
                validate_non_zero_grand_total(
                    _Doc(
                        grand_total=0,
                        total=59.8,
                        discount_amount=359.8,
                        custom_applied_gift_cards=[
                            {"gift_card_code": "GIFTU90E", "redeemed_amount": 300},
                            {"gift_card_code": "GIFTOTJQ", "redeemed_amount": 59.8},
                        ],
                    )
                )

    def test_gift_cards_present_but_nothing_to_reduce_is_rejected(self):
        with patch(f"{_MODULE}.resolve_applied_coupon_code", return_value=""):
            with patch(f"{_MODULE}.invoice_has_applied_gift_cards", return_value=True):
                with self.assertRaises(frappe.ValidationError):
                    validate_non_zero_grand_total(
                        _Doc(
                            grand_total=0,
                            total=0,
                            discount_amount=0,
                            custom_applied_gift_cards=[
                                {"gift_card_code": "GIFTU90E", "redeemed_amount": 0},
                            ],
                        )
                    )

    def test_coupon_present_but_nothing_to_reduce_is_rejected(self):
        # A coupon is attached but the subtotal was already zero (free items):
        # the coupon did not reduce anything, so it is still rejected.
        with patch(f"{_MODULE}.resolve_applied_coupon_code", return_value="SAVE10"):
            with self.assertRaises(frappe.ValidationError):
                validate_non_zero_grand_total(_Doc(grand_total=0, total=0, discount_amount=0))

    def test_return_is_exempt(self):
        # Credit notes / returns are naturally zero-or-negative.
        with patch(f"{_MODULE}.resolve_applied_coupon_code", return_value=""):
            validate_non_zero_grand_total(
                _Doc(grand_total=0, is_return=1, total=0, discount_amount=0)
            )
