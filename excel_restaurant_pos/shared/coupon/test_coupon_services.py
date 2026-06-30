# Copyright (c) 2026, Excel and Contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.coupon.services import (
    build_coupon_code,
    calculate_validity_dates,
    is_channel_allowed,
    resolve_validity_dates,
)


class TestCouponServices(FrappeTestCase):
    def test_pos_channel_matching(self):
        self.assertTrue(is_channel_allowed("Table", "Dine-in", "POS"))
        self.assertTrue(is_channel_allowed("In Store", "Delivery", "POS"))
        self.assertFalse(is_channel_allowed("Website", "Pickup", "POS"))

    def test_online_channel_matching(self):
        self.assertTrue(is_channel_allowed("Website", "Pickup", "Online Pickup"))
        self.assertTrue(is_channel_allowed("Website", "Delivery", "Only Online"))
        self.assertFalse(is_channel_allowed("Table", "Takeout", "Only Online"))

    def test_coupon_code_template_removes_separators(self):
        coupon_code = build_coupon_code("SAVE26-####")
        self.assertRegex(coupon_code, r"^SAVE26[A-Z0-9]{4}$")

    def test_validity_dates_use_expire_after_days(self):
        valid_from, valid_upto = calculate_validity_dates(90)
        self.assertIsNotNone(valid_from)
        self.assertIsNotNone(valid_upto)

    def test_resolve_validity_dates_from_override(self):
        class Settings:
            expire_after_days = None

        valid_from, valid_upto = resolve_validity_dates(Settings(), {"expire_after_days": 30})
        self.assertIsNotNone(valid_from)
        self.assertIsNotNone(valid_upto)
