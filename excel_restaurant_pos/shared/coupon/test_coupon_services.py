# Copyright (c) 2026, Excel and Contributors
# See license.txt

import frappe
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

    def test_cap_flat_discount_floors_invoice_at_zero(self):
        """A flat discount is capped to its base so the invoice never goes negative."""
        from excel_restaurant_pos.shared.coupon.services import _cap_flat_discount

        class Doc:
            def __init__(self, **kw):
                self._d = kw

            def get(self, k, default=None):
                return self._d.get(k, default)

        net = Doc(apply_discount_on="Net Total", net_total=10)
        # Over-total flat discount is capped to the net total (invoice -> 0).
        self.assertEqual(_cap_flat_discount(net, 15), 10)
        # Within-total flat discount is untouched.
        self.assertEqual(_cap_flat_discount(net, 7), 7)
        # Exact-total flat discount is untouched.
        self.assertEqual(_cap_flat_discount(net, 10), 10)

    def _fake_doc(self, **kw):
        import frappe

        class FakeDoc(dict):
            def __init__(self, **fields):
                super().__init__(**fields)
                self.flags = frappe._dict()

            def __getattr__(self, k):
                try:
                    return self[k]
                except KeyError:
                    raise AttributeError(k)

            def __setattr__(self, k, v):
                if k == "flags":
                    super().__setattr__(k, v)
                else:
                    self[k] = v

        return FakeDoc(**kw)

    def test_reset_preserves_manual_discount_in_other_field(self):
        """Removing a flat coupon must not wipe a manual percentage discount."""
        from unittest.mock import patch

        from excel_restaurant_pos.shared.coupon import services

        doc = self._fake_doc(
            custom_coupon_code="OLD",
            coupon_code="OLD",
            discount_amount=0,          # flat coupon's field, but currently empty
            additional_discount_percentage=20,  # user's manual discount
            items=[],
        )
        flat_coupon = frappe._dict(custom_discount_type="Flat Amount", custom_discount_amount=10)
        with patch.object(services, "_load_coupon", return_value=flat_coupon):
            services._reset_coupon_discount_state(doc, removed_coupon="OLD")
        self.assertEqual(doc.additional_discount_percentage, 20)
        self.assertIsNone(doc.custom_coupon_code)

    def test_reset_clears_only_matching_coupon_discount(self):
        """The coupon's own discount clears; a changed (manual) value is kept."""
        from unittest.mock import patch

        from excel_restaurant_pos.shared.coupon import services

        flat_coupon = frappe._dict(custom_discount_type="Flat Amount", custom_discount_amount=10)

        # Value still equals the coupon's -> it is the coupon's discount -> cleared.
        matching = self._fake_doc(
            custom_coupon_code="OLD", coupon_code="OLD",
            discount_amount=10, additional_discount_percentage=0,
            apply_discount_on="Net Total", net_total=100, items=[],
        )
        with patch.object(services, "_load_coupon", return_value=flat_coupon):
            services._reset_coupon_discount_state(matching, removed_coupon="OLD")
        self.assertEqual(matching.discount_amount, 0)

        # Value was changed by the user -> it is a manual discount -> preserved.
        manual = self._fake_doc(
            custom_coupon_code="OLD", coupon_code="OLD",
            discount_amount=7, additional_discount_percentage=0,
            apply_discount_on="Net Total", net_total=100, items=[],
        )
        with patch.object(services, "_load_coupon", return_value=flat_coupon):
            services._reset_coupon_discount_state(manual, removed_coupon="OLD")
        self.assertEqual(manual.discount_amount, 7)

    def test_reset_unresolvable_coupon_full_reset(self):
        """An unresolvable coupon falls back to a full reset so nothing lingers."""
        from unittest.mock import patch

        from excel_restaurant_pos.shared.coupon import services

        doc = self._fake_doc(
            custom_coupon_code="OLD", coupon_code="OLD",
            discount_amount=10, additional_discount_percentage=5, items=[],
        )
        with patch.object(services, "_load_coupon", return_value=None):
            services._reset_coupon_discount_state(doc, removed_coupon="OLD")
        self.assertEqual(doc.discount_amount, 0)
        self.assertEqual(doc.additional_discount_percentage, 0)

