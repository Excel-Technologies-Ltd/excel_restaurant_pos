# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.gift_card.admin import (
	_parse_import_rows,
	generate_bulk_inactive_gift_cards,
	import_inactive_gift_cards,
)


class TestGiftCardAdmin(FrappeTestCase):
	def test_parse_import_with_headers(self):
		rows = _parse_import_rows("code,amount,email\nGIFT1,1000,a@b.com\n,2000,\n")
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["code"], "GIFT1")
		self.assertEqual(rows[0]["amount"], "1000")
		self.assertEqual(rows[1]["code"], "")
		self.assertEqual(rows[1]["amount"], "2000")

	def test_parse_import_code_amount(self):
		rows = _parse_import_rows("CODEA,1500\nCODEB,2500")
		self.assertEqual(rows[0]["code"], "CODEA")
		self.assertEqual(rows[0]["amount"], "1500")

	@patch("excel_restaurant_pos.shared.gift_card.admin._create_inactive_gift_card")
	@patch("excel_restaurant_pos.shared.gift_card.admin._validate_gift_pricing_rule", return_value="PR-GIFT")
	@patch("excel_restaurant_pos.shared.gift_card.admin.get_gift_card_settings")
	def test_generate_bulk(self, get_settings, _pricing, create_card):
		get_settings.return_value = frappe._dict(gift_card_prefix="GIFT####")
		create_card.side_effect = lambda **kwargs: f"GIFT{create_card.call_count}"

		result = generate_bulk_inactive_gift_cards(3, 1000)
		self.assertEqual(result["created_count"], 3)
		self.assertEqual(len(result["codes"]), 3)
		self.assertEqual(create_card.call_count, 3)

	@patch("excel_restaurant_pos.shared.gift_card.admin._create_inactive_gift_card")
	@patch("excel_restaurant_pos.shared.gift_card.admin._validate_gift_pricing_rule", return_value="PR-GIFT")
	@patch("excel_restaurant_pos.shared.gift_card.admin.get_gift_card_settings")
	def test_import_creates_rows(self, get_settings, _pricing, create_card):
		get_settings.return_value = frappe._dict(gift_card_prefix="GIFT####")
		create_card.side_effect = lambda **kwargs: kwargs.get("coupon_code") or f"AUTO{create_card.call_count}"

		result = import_inactive_gift_cards("code,amount\nIMP1,500\n,750\n")
		self.assertEqual(result["created_count"], 2)
		self.assertEqual(result["error_count"], 0)

	def test_bulk_rejects_zero_qty(self):
		with self.assertRaises(Exception):
			generate_bulk_inactive_gift_cards(0, 100)

	def test_parse_import_with_expiry_header(self):
		rows = _parse_import_rows("code,amount,email,expiry\nGIFT1,1000,a@b.com,2099-12-31\n,2000,,\n")
		self.assertEqual(rows[0]["expiry"], "2099-12-31")
		self.assertEqual(rows[1]["expiry"], "")

	@patch("excel_restaurant_pos.shared.gift_card.admin._create_inactive_gift_card")
	@patch("excel_restaurant_pos.shared.gift_card.admin._validate_gift_pricing_rule", return_value="PR-GIFT")
	@patch("excel_restaurant_pos.shared.gift_card.admin.get_gift_card_settings")
	def test_generate_bulk_stamps_expiry(self, get_settings, _pricing, create_card):
		get_settings.return_value = frappe._dict(gift_card_prefix="GIFT####")
		create_card.side_effect = lambda **kwargs: f"GIFT{create_card.call_count}"

		result = generate_bulk_inactive_gift_cards(2, 1000, valid_upto="2099-12-31")

		self.assertEqual(result["valid_upto"], "2099-12-31")
		for call in create_card.call_args_list:
			self.assertEqual(str(call.kwargs["valid_upto"]), "2099-12-31")

	@patch("excel_restaurant_pos.shared.gift_card.admin._create_inactive_gift_card")
	@patch("excel_restaurant_pos.shared.gift_card.admin._validate_gift_pricing_rule", return_value="PR-GIFT")
	@patch("excel_restaurant_pos.shared.gift_card.admin.get_gift_card_settings")
	def test_import_row_expiry_overrides_default(self, get_settings, _pricing, create_card):
		get_settings.return_value = frappe._dict(gift_card_prefix="GIFT####")
		create_card.side_effect = lambda **kwargs: kwargs.get("coupon_code") or f"AUTO{create_card.call_count}"

		import_inactive_gift_cards(
			"code,amount,expiry\nIMP1,500,2099-01-31\n,750,\n", valid_upto="2099-12-31"
		)

		self.assertEqual(str(create_card.call_args_list[0].kwargs["valid_upto"]), "2099-01-31")
		self.assertEqual(str(create_card.call_args_list[1].kwargs["valid_upto"]), "2099-12-31")

	def test_bulk_rejects_past_expiry(self):
		with self.assertRaises(Exception):
			generate_bulk_inactive_gift_cards(1, 100, valid_upto="2000-01-01")
