# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.item.get_item_list import (
    GIFT_CARD_ITEM_FIELD,
    PAGINATION_KEYS,
    _build_base_filters,
    _build_list_query_params,
    _gift_card_filter,
)

MODULE = "excel_restaurant_pos.api.item.get_item_list"


class TestGiftCardItemFilter(FrappeTestCase):
    def setUp(self):
        frappe.local.form_dict = frappe._dict(cmd="api.items.list")

    def test_field_is_on_the_item_doctype(self):
        self.assertIn(GIFT_CARD_ITEM_FIELD, {df.fieldname for df in frappe.get_meta("Item").fields})

    def test_omitting_the_parameter_changes_nothing(self):
        self.assertIsNone(_gift_card_filter())
        self.assertEqual(
            _build_base_filters(), [["variant_of", "is", "not set"], ["disabled", "=", 0]]
        )

    def test_gift_card_items_only(self):
        frappe.local.form_dict[GIFT_CARD_ITEM_FIELD] = "1"
        self.assertEqual(_gift_card_filter(), [GIFT_CARD_ITEM_FIELD, "=", 1])
        self.assertIn([GIFT_CARD_ITEM_FIELD, "=", 1], _build_base_filters())

    def test_non_gift_card_items_only(self):
        frappe.local.form_dict[GIFT_CARD_ITEM_FIELD] = "0"
        self.assertEqual(_gift_card_filter(), [GIFT_CARD_ITEM_FIELD, "=", 0])
        self.assertIn([GIFT_CARD_ITEM_FIELD, "=", 0], _build_base_filters())

    def test_blank_parameter_is_not_a_filter(self):
        frappe.local.form_dict[GIFT_CARD_ITEM_FIELD] = ""
        self.assertIsNone(_gift_card_filter())

    def test_field_also_works_inside_filters(self):
        frappe.local.form_dict["filters"] = f'[["{GIFT_CARD_ITEM_FIELD}", "=", 1]]'
        self.assertIn([GIFT_CARD_ITEM_FIELD, "=", 1], _build_base_filters())

    def test_parameter_combines_with_other_filters(self):
        frappe.local.form_dict["filters"] = '[["item_group", "=", "Snacks"]]'
        frappe.local.form_dict[GIFT_CARD_ITEM_FIELD] = "1"

        filters = _build_base_filters()
        self.assertIn(["item_group", "=", "Snacks"], filters)
        self.assertIn([GIFT_CARD_ITEM_FIELD, "=", 1], filters)

    def test_dict_filters_are_accepted(self):
        """`filters` as a dict used to raise AttributeError on .extend()."""
        frappe.local.form_dict["filters"] = '{"item_group": "Snacks"}'
        self.assertIn(["item_group", "=", "Snacks"], _build_base_filters())

    def test_missing_field_gives_a_clear_error(self):
        frappe.local.form_dict[GIFT_CARD_ITEM_FIELD] = "1"
        with patch(f"{MODULE}._item_fieldnames", return_value={"item_code"}):
            with self.assertRaises(frappe.ValidationError):
                _gift_card_filter()


class TestConsumedKeys(FrappeTestCase):
    def test_the_parameter_never_reaches_the_query_builder(self):
        """form_dict is splatted into get_all, where an unknown kwarg is a TypeError."""
        self.assertIn(GIFT_CARD_ITEM_FIELD, PAGINATION_KEYS)

        frappe.local.form_dict = frappe._dict(
            cmd="api.items.list", item_group="Snacks", **{GIFT_CARD_ITEM_FIELD: "1"}
        )
        params = _build_list_query_params([], 0, 10)

        self.assertNotIn(GIFT_CARD_ITEM_FIELD, params)
        self.assertEqual(params["item_group"], "Snacks")
