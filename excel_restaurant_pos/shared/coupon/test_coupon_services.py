# Copyright (c) 2026, Excel and Contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.coupon.services import (
    build_coupon_code,
    calculate_validity_dates,
    is_channel_allowed,
    is_online_order,
    resolve_validity_dates,
)


class TestCouponServices(FrappeTestCase):
    def test_pos_channel_matching(self):
        self.assertTrue(is_channel_allowed("Table", "Dine-in", "POS"))
        self.assertTrue(is_channel_allowed("In Store", "Pickup", "POS"))
        self.assertTrue(is_channel_allowed("In Store", "Delivery", "POS"))
        self.assertFalse(is_channel_allowed("Website", "Pickup", "POS"))

    def test_online_channel_matching(self):
        self.assertTrue(is_channel_allowed("Website", "Pickup", "Online Pickup"))
        self.assertTrue(is_channel_allowed("Website", "Delivery", "Only Online"))
        self.assertFalse(is_channel_allowed("Table", "Takeout", "Only Online"))

    def test_is_online_order_requires_website_pickup_or_delivery(self):
        class Doc:
            def __init__(self, order_from, service_type):
                self._data = {
                    "custom_order_from": order_from,
                    "custom_service_type": service_type,
                }

            def get(self, key, default=None):
                return self._data.get(key, default)

        self.assertTrue(is_online_order(Doc("Website", "Pickup")))
        self.assertTrue(is_online_order(Doc("Website", "Delivery")))
        self.assertFalse(is_online_order(Doc("Website", "Dine-in")))
        self.assertFalse(is_online_order(Doc("Table", "Takeout")))
        self.assertFalse(is_online_order(Doc("In Store", "Pickup")))

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

    def test_is_generation_allowed_subtotal_check(self):
        from unittest.mock import patch

        class Settings:
            allow_auto_generate_cc = 1
            auto_generate_on = "All"
            minimum_subtotal_generate = 50.0

        class Doc:
            def __init__(self, order_from, service_type, subtotal):
                self._data = {
                    "custom_order_from": order_from,
                    "custom_service_type": service_type,
                    "net_total": subtotal,
                    "name": "test-sales-invoice",
                }

            def get(self, key, default=None):
                return self._data.get(key, default)

        settings = Settings()

        # Test online order below minimum subtotal (should not be allowed)
        doc_online_below = Doc("Website", "Pickup", 30.0)
        # Test online order above/equal minimum subtotal (should be allowed)
        doc_online_above = Doc("Website", "Pickup", 60.0)

        # Test POS order below minimum subtotal (should not be allowed)
        doc_pos_below = Doc("In Store", "Pickup", 30.0)
        # Test POS order above/equal minimum subtotal (should be allowed)
        doc_pos_above = Doc("In Store", "Pickup", 60.0)

        with patch("excel_restaurant_pos.shared.coupon.services.get_existing_generated_coupon", return_value=None):
            from excel_restaurant_pos.shared.coupon.services import is_generation_allowed

            # auto_generate_on is "All" here, so the minimum net total is what decides.
            # It applies to every allowed channel, online and POS alike.
            self.assertFalse(is_generation_allowed(doc_online_below, settings))
            self.assertTrue(is_generation_allowed(doc_online_above, settings))
            self.assertFalse(is_generation_allowed(doc_pos_below, settings))
            self.assertTrue(is_generation_allowed(doc_pos_above, settings))

    def test_is_generation_allowed_honours_auto_generate_on(self):
        """auto_generate_on must gate the channel even when everything else passes."""
        from unittest.mock import patch

        class Settings:
            allow_auto_generate_cc = 1
            minimum_subtotal_generate = 50.0

            def __init__(self, auto_generate_on):
                self.auto_generate_on = auto_generate_on

        class Doc:
            def __init__(self, order_from, service_type):
                self._data = {
                    "custom_order_from": order_from,
                    "custom_service_type": service_type,
                    "net_total": 100.0,  # comfortably over the minimum
                    "name": "test-sales-invoice",
                }

            def get(self, key, default=None):
                return self._data.get(key, default)

        online = Doc("Website", "Pickup")
        pos = Doc("In Store", "Pickup")

        with patch("excel_restaurant_pos.shared.coupon.services.get_existing_generated_coupon", return_value=None):
            from excel_restaurant_pos.shared.coupon.services import is_generation_allowed

            # Only Online: POS orders must not generate, however large.
            self.assertTrue(is_generation_allowed(online, Settings("Only Online")))
            self.assertFalse(is_generation_allowed(pos, Settings("Only Online")))

            # POS: online orders must not generate.
            self.assertFalse(is_generation_allowed(online, Settings("POS")))
            self.assertTrue(is_generation_allowed(pos, Settings("POS")))

            # All: both generate.
            self.assertTrue(is_generation_allowed(online, Settings("All")))
            self.assertTrue(is_generation_allowed(pos, Settings("All")))

            # Unset: nothing generates.
            self.assertFalse(is_generation_allowed(online, Settings("")))
            self.assertFalse(is_generation_allowed(pos, Settings("")))

