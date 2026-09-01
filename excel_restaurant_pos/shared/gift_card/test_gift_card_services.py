# Copyright (c) 2026, Excel and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.gift_card.services import (
	is_gift_card_generation_allowed,
	is_gift_card_redemption_channel_allowed,
	recompute_available_balance,
	_resolve_gift_card_customer,
)
from excel_restaurant_pos.shared.gift_card.redemption import validate_gift_card_globally
from excel_restaurant_pos.shared.gift_card.validation import (
	GIFT_CARD_TYPE_EXISTING,
	GIFT_CARD_TYPE_NEW,
	get_gift_card_lines,
	resolve_line_gift_amount,
)


def _settings(**flags):
	defaults = {
		"no_by_sales": 0,
		"dine_in_by_sales": 0,
		"in_store_pickup_by_sales": 0,
		"online_delivery_by_sales": 0,
		"online_pickup_by_sales": 0,
		"dine_in_gift_redeem": 0,
		"in_store_pickup_gift_redeem": 0,
		"online_delivery_gift_redeem": 0,
		"online_pickup_gift_redeem": 0,
	}
	defaults.update(flags)
	return frappe._dict(defaults)


def _invoice(order_from, service_type):
	return frappe._dict(custom_order_from=order_from, custom_service_type=service_type)


class TestGiftCardCustomer(FrappeTestCase):
	def test_resolve_customer_from_invoice(self):
		invoice = frappe._dict(customer="CUST-001")
		self.assertEqual(_resolve_gift_card_customer(invoice), "CUST-001")

	@patch("excel_restaurant_pos.shared.gift_card.services.get_gift_card_settings")
	def test_resolve_customer_from_settings(self, get_settings):
		get_settings.return_value = frappe._dict(customer="WALK-IN")
		self.assertEqual(_resolve_gift_card_customer(), "WALK-IN")

	@patch("excel_restaurant_pos.shared.gift_card.services.get_gift_card_settings", return_value=None)
	def test_resolve_customer_missing_raises(self, _get_settings):
		with self.assertRaises(frappe.MandatoryError):
			_resolve_gift_card_customer()


class TestGiftCardChannelGates(FrappeTestCase):
	def test_no_by_sales_blocks_all_generation(self):
		settings = _settings(no_by_sales=1, dine_in_by_sales=1)
		self.assertFalse(is_gift_card_generation_allowed(_invoice("Table", "Dine-in"), settings))

	def test_dine_in_generation_flag(self):
		settings = _settings(dine_in_by_sales=1)
		self.assertTrue(is_gift_card_generation_allowed(_invoice("Table", "Dine-in"), settings))
		self.assertTrue(is_gift_card_generation_allowed(_invoice("Table", "Takeout"), settings))
		self.assertFalse(is_gift_card_generation_allowed(_invoice("Website", "Pickup"), settings))

	def test_online_pickup_generation_flag(self):
		settings = _settings(online_pickup_by_sales=1)
		self.assertTrue(is_gift_card_generation_allowed(_invoice("Website", "Pickup"), settings))
		self.assertFalse(is_gift_card_generation_allowed(_invoice("Website", "Delivery"), settings))

	def test_redemption_channel_flags(self):
		settings = _settings(in_store_pickup_gift_redeem=1, online_delivery_gift_redeem=1)
		self.assertTrue(
			is_gift_card_redemption_channel_allowed(_invoice("In Store", "Pickup"), settings)
		)
		self.assertTrue(
			is_gift_card_redemption_channel_allowed(_invoice("Website", "Delivery"), settings)
		)
		self.assertFalse(
			is_gift_card_redemption_channel_allowed(_invoice("Table", "Dine-in"), settings)
		)

	@patch("excel_restaurant_pos.shared.gift_card.services.get_gift_card_settings", return_value=None)
	def test_missing_settings_blocks_generation(self, _get_settings):
		self.assertFalse(is_gift_card_generation_allowed(_invoice("Table", "Dine-in"), None))


class TestGiftCardLines(FrappeTestCase):
	def test_get_gift_card_lines_filters(self):
		doc = frappe._dict(
			items=[
				frappe._dict(custom_is_gift_card_item=1, item_code="GIFT"),
				frappe._dict(custom_is_gift_card_item=0, item_code="FOOD"),
				{"custom_is_gift_card_item": 1, "item_code": "GIFT2"},
			]
		)
		lines = get_gift_card_lines(doc)
		self.assertEqual(len(lines), 2)

	def test_resolve_new_line_amount_from_line(self):
		line = {"custom_gift_card_type": GIFT_CARD_TYPE_NEW, "custom_gift_amount": 1500}
		self.assertEqual(resolve_line_gift_amount(line), 1500)

	@patch("excel_restaurant_pos.shared.gift_card.validation.frappe.db.get_value")
	def test_resolve_new_line_amount_from_item(self, get_value):
		get_value.return_value = 2000
		line = {
			"custom_gift_card_type": GIFT_CARD_TYPE_NEW,
			"custom_gift_amount": 0,
			"item_code": "GIFT-2000",
		}
		self.assertEqual(resolve_line_gift_amount(line), 2000)
		get_value.assert_called_with("Item", "GIFT-2000", "custom_gift_card_value")

	@patch("excel_restaurant_pos.shared.gift_card.validation.normalize_coupon_name")
	@patch("excel_restaurant_pos.shared.gift_card.validation.frappe.db.get_value")
	def test_resolve_existing_from_coupon(self, get_value, normalize):
		normalize.return_value = "GIFTABC"
		get_value.return_value = 750
		line = {
			"custom_gift_card_type": GIFT_CARD_TYPE_EXISTING,
			"custom_gift_card_code": "GIFTABC",
			"custom_gift_amount": 0,
			"custom_coupon_value": 0,
		}
		self.assertEqual(resolve_line_gift_amount(line), 750)


	@patch("excel_restaurant_pos.shared.gift_card.services.create_gift_card_coupon")
	@patch("excel_restaurant_pos.shared.gift_card.services.get_gift_card_settings")
	@patch("excel_restaurant_pos.shared.gift_card.services.is_gift_card_generation_allowed", return_value=True)
	def test_process_gift_cards_on_submit_new_type(self, _allowed, get_settings, create_coupon):
		from excel_restaurant_pos.shared.gift_card.services import process_gift_cards_on_submit

		get_settings.return_value = frappe._dict()
		create_coupon.return_value = frappe._dict(name="GIFT-NEW")
		doc = frappe._dict(
			customer="CUST-1",
			items=[
				frappe._dict(
					custom_is_gift_card_item=1,
					custom_gift_card_type=GIFT_CARD_TYPE_NEW,
					custom_gift_amount=1000,
					item_code="GIFT",
					qty=1,
				)
			],
			custom_generated_gift_cards="",
		)

		process_gift_cards_on_submit(doc)
		self.assertEqual(doc.custom_generated_gift_cards, "GIFT-NEW")
		create_coupon.assert_called_once()

	@patch("excel_restaurant_pos.shared.gift_card.services._gift_validity_dates", return_value=("2026-01-01", "2027-01-01"))
	@patch("excel_restaurant_pos.shared.gift_card.services._resolve_gift_card_customer", return_value="CUST-1")
	@patch("excel_restaurant_pos.shared.gift_card.services.get_gift_card_email", return_value="buyer@example.com")
	def test_activate_existing_gift_card_defers_invoice_link(self, _email, _customer, _dates):
		from excel_restaurant_pos.shared.gift_card.services import activate_existing_gift_card

		coupon = SimpleNamespace(
			custom_discount_amount=500,
			custom_linked_email="",
			custom_discount_type="Flat Amount",
			flags=SimpleNamespace(),
			save=MagicMock(),
		)
		invoice = frappe._dict(name="ORD-26-02285", posting_date="2026-08-31")

		activate_existing_gift_card(coupon, invoice, frappe._dict())

		self.assertFalse(hasattr(coupon, "custom_generated_on_order"))
		self.assertEqual(coupon.flags.generated_for_invoice, "ORD-26-02285")
		coupon.save.assert_called_once_with(ignore_permissions=True)


class TestGiftCardBalance(FrappeTestCase):
	def test_recompute_partial_keeps_active(self):
		coupon = MagicMock()
		coupon.custom_discount_amount = 1000
		coupon.custom_status = "Active"
		coupon.get.return_value = [
			SimpleNamespace(redeemed_amount=400),
		]

		balance = recompute_available_balance(coupon, save=True)
		self.assertEqual(balance, 600)
		self.assertEqual(coupon.custom_available_balance, 600)
		self.assertEqual(coupon.custom_status, "Active")
		coupon.save.assert_called_once()

	def test_recompute_full_sets_used(self):
		coupon = MagicMock()
		coupon.custom_discount_amount = 1000
		coupon.custom_status = "Active"
		coupon.get.return_value = [
			SimpleNamespace(redeemed_amount=600),
			SimpleNamespace(redeemed_amount=400),
		]

		balance = recompute_available_balance(coupon, save=False)
		self.assertEqual(balance, 0)
		self.assertEqual(coupon.custom_status, "Used")
		coupon.save.assert_not_called()

	def test_recompute_does_not_override_rejected(self):
		coupon = MagicMock()
		coupon.custom_discount_amount = 1000
		coupon.custom_status = "Rejected"
		coupon.get.return_value = [SimpleNamespace(redeemed_amount=1000)]

		recompute_available_balance(coupon, save=False)
		self.assertEqual(coupon.custom_status, "Rejected")


class TestGiftCardRedemptionMath(FrappeTestCase):
	def test_sum_and_remaining_multi_card(self):
		from excel_restaurant_pos.shared.gift_card.redemption import (
			remaining_gift_redeemable,
			sum_applied_gift_amounts,
		)

		doc = frappe._dict(
			total=1500,
			net_total=1500,
			grand_total=1500,
			custom_applied_gift_cards=[
				frappe._dict(gift_card_code="GIFT-A", redeemed_amount=1000),
				frappe._dict(gift_card_code="GIFT-B", redeemed_amount=500),
			],
		)
		self.assertEqual(sum_applied_gift_amounts(doc), 1500)
		self.assertEqual(remaining_gift_redeemable(doc), 0)
		self.assertEqual(remaining_gift_redeemable(doc, exclude_code="GIFT-B"), 500)

	def test_parse_gift_card_codes_multi(self):
		from excel_restaurant_pos.shared.gift_card.redemption import parse_gift_card_codes

		self.assertEqual(parse_gift_card_codes("A, B\nC"), ["A", "B", "C"])
		self.assertEqual(parse_gift_card_codes(["A", "B", "A"]), ["A", "B"])
		self.assertEqual(parse_gift_card_codes("A;B", ["C"]), ["A", "B", "C"])
		self.assertEqual(parse_gift_card_codes(""), [])

	def test_invoice_has_promo_vs_gift(self):
		from excel_restaurant_pos.shared.gift_card.redemption import (
			assert_no_gift_cards,
			assert_no_promo_coupon,
			invoice_has_applied_gift_cards,
		)

		with_gifts = frappe._dict(
			custom_applied_gift_cards=[frappe._dict(gift_card_code="G1", redeemed_amount=10)],
			custom_coupon_code=None,
		)
		self.assertTrue(invoice_has_applied_gift_cards(with_gifts))
		with self.assertRaises(frappe.ValidationError):
			assert_no_gift_cards(with_gifts)

		empty = frappe._dict(custom_applied_gift_cards=[], custom_coupon_code=None)
		assert_no_gift_cards(empty)
		assert_no_promo_coupon(empty)


class TestGiftCardGlobalVerify(FrappeTestCase):
	@patch("excel_restaurant_pos.shared.gift_card.redemption._assert_gift_card_redeemable_balance", return_value=750.0)
	@patch("excel_restaurant_pos.shared.gift_card.redemption._load_active_gift_card")
	def test_validate_gift_card_globally(self, load_card, _balance):
		load_card.return_value = frappe._dict(
			name="GIFT-ABC",
			coupon_code="GIFT-ABC",
			valid_from="2026-01-01",
			valid_upto="2027-01-01",
			custom_status="Active",
		)

		result = validate_gift_card_globally("GIFT-ABC")

		self.assertTrue(result["valid"])
		self.assertEqual(result["gift_card_code"], "GIFT-ABC")
		self.assertEqual(result["available_balance"], 750.0)
		load_card.assert_called_once_with("GIFT-ABC")
