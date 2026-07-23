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

    def test_dine_in_redemption_channel(self):
        """'Dine-in' allows only Table / Dine-in orders."""
        self.assertTrue(is_channel_allowed("Table", "Dine-in", "Dine-in"))
        self.assertFalse(is_channel_allowed("Table", "Takeout", "Dine-in"))
        self.assertFalse(is_channel_allowed("In Store", "Pickup", "Dine-in"))
        self.assertFalse(is_channel_allowed("Website", "Pickup", "Dine-in"))

    def test_in_store_pickup_redemption_channel(self):
        """'In Store Pickup' allows only In Store / Pickup orders."""
        self.assertTrue(is_channel_allowed("In Store", "Pickup", "In Store Pickup"))
        self.assertFalse(is_channel_allowed("In Store", "Delivery", "In Store Pickup"))
        self.assertFalse(is_channel_allowed("Table", "Dine-in", "In Store Pickup"))
        self.assertFalse(is_channel_allowed("Website", "Pickup", "In Store Pickup"))

    def test_existing_redemption_channels_unchanged(self):
        """Regression: the pre-existing options keep their exact behaviour."""
        # POS covers every in-restaurant channel, no online.
        self.assertTrue(is_channel_allowed("Table", "Dine-in", "POS"))
        self.assertTrue(is_channel_allowed("In Store", "Pickup", "POS"))
        self.assertFalse(is_channel_allowed("Website", "Pickup", "POS"))
        # All covers everything; unknown/blank cover nothing.
        self.assertTrue(is_channel_allowed("Table", "Dine-in", "All"))
        self.assertTrue(is_channel_allowed("Website", "Delivery", "All"))
        self.assertFalse(is_channel_allowed("Table", "Dine-in", ""))
        self.assertFalse(is_channel_allowed("Table", "Dine-in", "Unknown Option"))

    def test_rejected_status_is_sticky(self):
        """A Rejected coupon is a terminal manual state -- refresh must never
        recompute it back to Active/Expired/Used, or it would become redeemable."""
        from excel_restaurant_pos.shared.coupon.services import (
            COUPON_STATUS_REJECTED,
            refresh_coupon_status,
        )

        class Coupon:
            def __init__(self, status):
                self.custom_status = status
                self.valid_upto = None   # would otherwise compute "Active"
                self.maximum_use = 0
                self.used = 0
                self.saved = False

            def save(self, **kwargs):
                self.saved = True

        rejected = Coupon(COUPON_STATUS_REJECTED)
        self.assertEqual(refresh_coupon_status(rejected, save=True), COUPON_STATUS_REJECTED)
        self.assertEqual(rejected.custom_status, COUPON_STATUS_REJECTED)
        self.assertFalse(rejected.saved)  # left untouched

        # A normal coupon still recomputes as before (regression).
        active = Coupon("Active")
        self.assertEqual(refresh_coupon_status(active, save=False), "Active")

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

        net = Doc(apply_discount_on="Net Total", total=10)
        # Over-total flat discount is capped to the subtotal (invoice -> 0).
        self.assertEqual(_cap_flat_discount(net, 15), 10)
        # Within-total flat discount is untouched.
        self.assertEqual(_cap_flat_discount(net, 7), 7)
        # Exact-total flat discount is untouched.
        self.assertEqual(_cap_flat_discount(net, 10), 10)

    def test_cap_measures_pre_discount_total_not_net_total(self):
        """Regression: the cap must measure against the pre-discount subtotal
        (`total`), not the already-discounted `net_total`. ERPNext reduces
        net_total once the discount is applied, so re-applying while reading
        net_total back would shrink a $15 coupon on a $17.99 order to $2.99."""
        from excel_restaurant_pos.shared.coupon.services import _cap_flat_discount

        class Doc:
            def __init__(self, **kw):
                self._d = kw

            def get(self, k, default=None):
                return self._d.get(k, default)

        # total stays 17.99; net_total has already been dropped to 2.99 by a
        # prior application. The $15 flat discount must survive in full.
        doc = Doc(apply_discount_on="Net Total", total=17.99, net_total=2.99)
        self.assertEqual(_cap_flat_discount(doc, 15), 15)

    def test_disc_upto_amount_caps_the_discount(self):
        """disc_upto_amount is the maximum discount for percentage and flat coupons."""
        from excel_restaurant_pos.shared.coupon.services import _coupon_effective_discount

        class Doc:
            def __init__(self, total):
                self._d = {"total": total, "apply_discount_on": "Net Total"}

            def get(self, k, default=None):
                return self._d.get(k, default)

        # Percentage 20%, cap $10.
        pct = frappe._dict(
            custom_discount_type="Percentage", custom_discount_amount=20, custom_disc_upto_amount=10
        )
        # below the cap: 20% of 30 = 6
        self.assertEqual(_coupon_effective_discount(Doc(30), pct), ("flat", 6.0))
        # equal to the cap: 20% of 50 = 10
        self.assertEqual(_coupon_effective_discount(Doc(50), pct), ("flat", 10.0))
        # above the cap: 20% of 100 = 20 -> capped to 10
        self.assertEqual(_coupon_effective_discount(Doc(100), pct), ("flat", 10.0))

        # Percentage with no cap stays a live percentage (scales with items).
        pct_nocap = frappe._dict(
            custom_discount_type="Percentage", custom_discount_amount=20, custom_disc_upto_amount=0
        )
        self.assertEqual(_coupon_effective_discount(Doc(100), pct_nocap), ("percentage", 20.0))

        # Flat coupon capped below its own amount.
        flat = frappe._dict(
            custom_discount_type="Flat Amount", custom_discount_amount=15, custom_disc_upto_amount=10
        )
        self.assertEqual(_coupon_effective_discount(Doc(100), flat), ("flat", 10.0))

        # Flat coupon, no cap -> full amount; still floored at the subtotal.
        flat_nocap = frappe._dict(
            custom_discount_type="Flat Amount", custom_discount_amount=15, custom_disc_upto_amount=0
        )
        self.assertEqual(_coupon_effective_discount(Doc(100), flat_nocap), ("flat", 15.0))
        self.assertEqual(_coupon_effective_discount(Doc(10), flat_nocap), ("flat", 10.0))

        # No discount value at all.
        empty = frappe._dict(
            custom_discount_type="Flat Amount", custom_discount_amount=0, custom_disc_upto_amount=10
        )
        self.assertEqual(_coupon_effective_discount(Doc(100), empty), (None, 0.0))

    def test_preview_caps_estimated_discount(self):
        """The preview estimate never reports a discount above the cap."""
        from excel_restaurant_pos.shared.coupon.services import preview_coupon_discount

        class Doc:
            def __init__(self, total):
                self._d = {"total": total, "net_total": total}

            def get(self, k, default=None):
                if k == "items":
                    return []
                return self._d.get(k, default)

        pct = frappe._dict(
            custom_discount_type="Percentage", custom_discount_amount=20, custom_disc_upto_amount=10
        )
        # 20% of 100 = 20, capped to 10.
        above = preview_coupon_discount(Doc(100), pct)
        self.assertEqual(above["discount_value"], 10.0)
        self.assertEqual(above["disc_upto_amount"], 10.0)
        # 20% of 30 = 6, below cap -> not capped.
        below = preview_coupon_discount(Doc(30), pct)
        self.assertEqual(below["discount_value"], 6.0)

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

    def test_reset_percentage_coupon_clears_derived_amount(self):
        """Removing a percentage coupon must clear both % and derived amount.

        ERPNext fills discount_amount from additional_discount_percentage. If we
        only zero the percentage, the orphaned amount remains and the invoice
        looks like a manual flat discount with percentage stuck at 0.
        """
        from unittest.mock import patch

        from excel_restaurant_pos.shared.coupon import services

        pct_coupon = frappe._dict(custom_discount_type="Percentage", custom_discount_amount=10)
        matching = self._fake_doc(
            custom_coupon_code="OLD",
            coupon_code="OLD",
            additional_discount_percentage=10,
            discount_amount=25,  # derived by calculate_taxes_and_totals
            apply_discount_on="Net Total",
            net_total=250,
            items=[],
        )
        with patch.object(services, "_load_coupon", return_value=pct_coupon):
            services._reset_coupon_discount_state(matching, removed_coupon="OLD")
        self.assertEqual(matching.additional_discount_percentage, 0)
        self.assertEqual(matching.discount_amount, 0)

        # Manual percentage different from the coupon rate must be preserved,
        # including whatever amount currently sits alongside it.
        manual = self._fake_doc(
            custom_coupon_code="OLD",
            coupon_code="OLD",
            additional_discount_percentage=20,
            discount_amount=50,
            apply_discount_on="Net Total",
            net_total=250,
            items=[],
        )
        with patch.object(services, "_load_coupon", return_value=pct_coupon):
            services._reset_coupon_discount_state(manual, removed_coupon="OLD")
        self.assertEqual(manual.additional_discount_percentage, 20)
        self.assertEqual(manual.discount_amount, 50)

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

    def _apply_hook_calls(self, stored, current, force):
        """Run apply_sales_invoice_coupon_discount with the DB/coupon layers mocked,
        and report whether the discount applier was invoked."""
        from unittest.mock import MagicMock, patch

        from excel_restaurant_pos.shared.coupon import services

        doc = self._fake_doc(custom_coupon_code=current, coupon_code=current, items=[])
        with patch.object(services, "resolve_applied_coupon_code", return_value=current), \
             patch.object(services, "_get_stored_applied_coupon", return_value=stored), \
             patch.object(services, "should_skip_redemption_validation", return_value=False), \
             patch.object(services, "_reset_coupon_discount_state"), \
             patch("frappe.get_doc", return_value=MagicMock()), \
             patch.object(services, "_apply_coupon_custom_discount", return_value=False) as apply_mock:
            services.apply_sales_invoice_coupon_discount(doc, force=force)
            return apply_mock.called

    def test_unchanged_coupon_not_reapplied_on_resave(self):
        """The reported bug: an unchanged coupon must NOT re-apply on an ordinary
        re-save, or it overwrites a manual discount the user typed."""
        # Same coupon already stored, plain save -> do not re-apply.
        self.assertFalse(self._apply_hook_calls(stored="SAVE10", current="SAVE10", force=False))

    def test_coupon_applies_when_new_changed_or_forced(self):
        """First add, a switch, or an explicit re-apply must apply the discount."""
        # Newly added (nothing stored yet).
        self.assertTrue(self._apply_hook_calls(stored="", current="SAVE10", force=False))
        # Switched to a different coupon.
        self.assertTrue(self._apply_hook_calls(stored="OLD", current="SAVE10", force=False))
        # Explicit re-apply (apply endpoint) on the same coupon.
        self.assertTrue(self._apply_hook_calls(stored="SAVE10", current="SAVE10", force=True))

