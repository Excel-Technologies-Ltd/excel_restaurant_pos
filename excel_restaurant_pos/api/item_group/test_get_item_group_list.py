# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.item_group.get_item_group_list import (
    _build_item_filters,
    _page_args,
    _requested_fields,
    _requested_filters,
    _requested_order_by,
    _wants_gift_cards,
    get_item_group_list,
)

PERMITTED = {"name", "item_group_name", "is_group", "custom_is_gift_card", "modified"}


class TestItemGroupListArgs(FrappeTestCase):
    def setUp(self):
        frappe.local.form_dict = frappe._dict()

    def test_unknown_request_args_are_ignored(self):
        """A stray sid / csrf_token / cache buster used to 500 the endpoint."""
        frappe.local.form_dict = frappe._dict(cmd="x", sid="abc", _="171", csrf_token="t")

        self.assertEqual(_requested_fields(PERMITTED), ["name"])
        self.assertEqual(_requested_filters(PERMITTED), [])
        self.assertIsNone(_requested_order_by(PERMITTED))
        self.assertEqual(_page_args(), (0, None))

    def test_unknown_field_is_rejected(self):
        frappe.local.form_dict = frappe._dict(fields='["name", "secret_column"]')
        with self.assertRaises(frappe.ValidationError):
            _requested_fields(PERMITTED)

    def test_wildcard_expands_to_known_columns(self):
        frappe.local.form_dict = frappe._dict(fields='["*"]')
        self.assertEqual(_requested_fields(PERMITTED), sorted(PERMITTED))

    def test_order_by_is_validated(self):
        frappe.local.form_dict = frappe._dict(order_by="item_group_name desc")
        self.assertEqual(_requested_order_by(PERMITTED), "`tabItem Group`.`item_group_name` desc")

        frappe.local.form_dict = frappe._dict(order_by="name; drop table x")
        with self.assertRaises(frappe.ValidationError):
            _requested_order_by(PERMITTED)

    def test_multi_column_order_by(self):
        frappe.local.form_dict = frappe._dict(order_by="custom_is_gift_card desc, name asc")
        self.assertEqual(
            _requested_order_by(PERMITTED),
            "`tabItem Group`.`custom_is_gift_card` desc, `tabItem Group`.`name` asc",
        )

    def test_dict_filters_are_accepted(self):
        """`filters` as a dict used to raise AttributeError on .extend()."""
        frappe.local.form_dict = frappe._dict(filters='{"is_group": 0}')
        self.assertEqual(_requested_filters(PERMITTED), [["is_group", "=", 0]])

    def test_filter_on_unknown_field_is_rejected(self):
        frappe.local.form_dict = frappe._dict(filters='[["secret_column", "=", 1]]')
        with self.assertRaises(frappe.ValidationError):
            _requested_filters(PERMITTED)

    def test_page_args_accept_the_usual_aliases(self):
        frappe.local.form_dict = frappe._dict(start="20", limit="10")
        self.assertEqual(_page_args(), (20, 10))


class TestGiftCardFilter(FrappeTestCase):
    def setUp(self):
        frappe.local.form_dict = frappe._dict()

    def test_gift_cards_excluded_by_default(self):
        self.assertFalse(_wants_gift_cards())
        self.assertIn(["custom_is_gift_card_item", "=", 0], _build_item_filters(False))

    def test_gift_cards_included_when_requested(self):
        frappe.local.form_dict = frappe._dict(custom_is_gift_card="1")
        self.assertTrue(_wants_gift_cards())
        filters = _build_item_filters(True)
        self.assertNotIn(["custom_is_gift_card_item", "=", 0], filters)

    def test_include_gift_cards_alias(self):
        frappe.local.form_dict = frappe._dict(include_gift_cards=1)
        self.assertTrue(_wants_gift_cards())

    def test_base_filters_are_always_applied(self):
        filters = _build_item_filters(True)
        self.assertIn(["variant_of", "is", "not set"], filters)
        self.assertIn(["disabled", "=", 0], filters)

    def test_combined_section_filter(self):
        frappe.local.form_dict = frappe._dict(custom_combined_section="Lunch")
        self.assertIn(
            ["custom_combined_section", "like", "%Lunch%"], _build_item_filters(True)
        )

    def test_item_filters_are_passed_through(self):
        frappe.local.form_dict = frappe._dict(item_filters='[["custom_is_website_item", "=", "1"]]')
        self.assertIn(["custom_is_website_item", "=", "1"], _build_item_filters(True))


class TestItemGroupListQuery(FrappeTestCase):
    def setUp(self):
        frappe.local.form_dict = frappe._dict()

    @patch("excel_restaurant_pos.api.item_group.get_item_group_list._candidate_group_names")
    def test_empty_candidates_skip_the_list_query(self, candidates):
        candidates.return_value = []
        with patch("excel_restaurant_pos.api.item_group.get_item_group_list.frappe.get_all") as get_all:
            self.assertEqual(get_item_group_list(), [])
            get_all.assert_not_called()

    @patch("excel_restaurant_pos.api.item_group.get_item_group_list._candidate_group_names")
    def test_group_names_are_scoped_to_the_query(self, candidates):
        candidates.return_value = ["Beverages", "Snacks"]
        with patch(
            "excel_restaurant_pos.api.item_group.get_item_group_list.frappe.get_all",
            return_value=[{"name": "Beverages"}],
        ) as get_all:
            get_item_group_list()

        kwargs = get_all.call_args.kwargs
        self.assertIn(["name", "in", ["Beverages", "Snacks"]], kwargs["filters"])
        self.assertEqual(kwargs["fields"], ["name"])
        # Omitted so the DocType default (modified desc) survives.
        self.assertNotIn("order_by", kwargs)

    @patch("excel_restaurant_pos.api.item_group.get_item_group_list.get_visible_item_group_names")
    @patch("excel_restaurant_pos.api.item_group.get_item_group_list._gift_card_group_names")
    def test_gift_card_groups_dropped_unless_requested(self, gift_groups, visible):
        from excel_restaurant_pos.api.item_group.get_item_group_list import _candidate_group_names

        gift_groups.return_value = ["Gift Cards"]
        visible.side_effect = lambda names: names

        with patch(
            "excel_restaurant_pos.api.item_group.get_item_group_list.frappe.get_all",
            return_value=["Beverages", "Gift Cards"],
        ):
            self.assertEqual(_candidate_group_names(False), ["Beverages"])
            self.assertEqual(_candidate_group_names(True), ["Beverages", "Gift Cards"])

    @patch("excel_restaurant_pos.api.item_group.get_item_group_list.get_visible_item_group_names")
    def test_item_query_is_distinct(self, visible):
        from excel_restaurant_pos.api.item_group.get_item_group_list import _candidate_group_names

        visible.side_effect = lambda names: names
        with patch(
            "excel_restaurant_pos.api.item_group.get_item_group_list.frappe.get_all",
            return_value=["Beverages"],
        ) as get_all:
            _candidate_group_names(True)

        self.assertTrue(get_all.call_args.kwargs["distinct"])
        self.assertEqual(get_all.call_args.kwargs["pluck"], "item_group")
        # DISTINCT on item_group plus the default ORDER BY modified is what
        # MySQL rejects under ONLY_FULL_GROUP_BY.
        self.assertIsNone(get_all.call_args.kwargs["order_by"])
