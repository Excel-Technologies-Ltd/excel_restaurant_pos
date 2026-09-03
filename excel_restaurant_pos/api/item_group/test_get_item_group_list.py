# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.item_group.get_item_group_list import (
    _build_item_filters,
    _gift_card_group_filter,
    _page_args,
    _requested_fields,
    _requested_filters,
    _requested_order_by,
    _validate_item_filters,
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

    def test_wildcard_is_passed_through(self):
        """The POS calls this endpoint with fields=["*"]."""
        frappe.local.form_dict = frappe._dict(fields='["*"]')
        self.assertEqual(_requested_fields(PERMITTED), ["*"])

    def test_bare_wildcard_string_is_passed_through(self):
        frappe.local.form_dict = frappe._dict(fields="*")
        self.assertEqual(_requested_fields(PERMITTED), ["*"])

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


class TestLiveRequestShape(FrappeTestCase):
    """The argument shape the POS actually sends today."""

    def setUp(self):
        frappe.local.form_dict = frappe._dict(
            # ?fields=["*"]&fields=* -- werkzeug keeps the first value
            fields='["*"]',
            filters='[["custom_publish_to_website","=","1"]]',
            item_filters=(
                '[["custom_is_website_item","=","1"],'
                '["custom_combined_section","like","%Bancan Kitchen%"]]'
            ),
            order_by="custom_priority asc",
        )

    def test_every_argument_survives(self):
        permitted = {"name", "custom_publish_to_website", "custom_priority"}

        self.assertEqual(_requested_fields(permitted), ["*"])
        self.assertEqual(
            _requested_filters(permitted), [["custom_publish_to_website", "=", "1"]]
        )
        self.assertEqual(
            _requested_order_by(permitted), "`tabItem Group`.`custom_priority` asc"
        )
        self.assertEqual(_page_args(), (0, None))

    def test_item_filters_reach_the_item_query(self):
        item_filters = _build_item_filters()
        self.assertIn(["custom_is_website_item", "=", "1"], item_filters)
        self.assertIn(
            ["custom_combined_section", "like", "%Bancan Kitchen%"], item_filters
        )


class TestGiftCardFilter(FrappeTestCase):
    def setUp(self):
        frappe.local.form_dict = frappe._dict()

    def test_no_gift_filter_by_default(self):
        """Omitting the parameter must not change what the endpoint returns."""
        self.assertIsNone(_gift_card_group_filter())
        self.assertNotIn(["custom_is_gift_card_item", "=", 0], _build_item_filters())

    def test_gift_card_groups_only(self):
        frappe.local.form_dict = frappe._dict(custom_is_gift_card="1")
        self.assertEqual(_gift_card_group_filter(), ["custom_is_gift_card", "=", 1])

    def test_non_gift_card_groups_only(self):
        frappe.local.form_dict = frappe._dict(custom_is_gift_card="0")
        self.assertEqual(_gift_card_group_filter(), ["custom_is_gift_card", "=", 0])

    def test_blank_parameter_is_not_a_filter(self):
        frappe.local.form_dict = frappe._dict(custom_is_gift_card="")
        self.assertIsNone(_gift_card_group_filter())

    def test_group_field_also_works_inside_filters(self):
        frappe.local.form_dict = frappe._dict(filters='[["custom_is_gift_card", "=", 1]]')
        permitted = {"name", "custom_is_gift_card"}
        self.assertEqual(_requested_filters(permitted), [["custom_is_gift_card", "=", 1]])

    def test_item_field_belongs_in_item_filters(self):
        frappe.local.form_dict = frappe._dict(
            item_filters='[["custom_is_gift_card_item", "=", 1]]'
        )
        self.assertIn(["custom_is_gift_card_item", "=", 1], _build_item_filters())

    def test_group_field_in_item_filters_is_rejected_with_a_hint(self):
        """The 500 that started this: custom_is_gift_card is not an Item column."""
        with self.assertRaises(frappe.ValidationError) as caught:
            _validate_item_filters([["custom_is_gift_card", "=", 1]])

        message = str(caught.exception)
        self.assertIn("custom_is_gift_card_item", message)
        self.assertIn("item_filters", message)

    def test_unknown_item_filter_field_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            _validate_item_filters([["not_a_column", "=", 1]])

    def test_base_filters_are_always_applied(self):
        filters = _build_item_filters()
        self.assertIn(["variant_of", "is", "not set"], filters)
        self.assertIn(["disabled", "=", 0], filters)

    def test_combined_section_filter(self):
        frappe.local.form_dict = frappe._dict(custom_combined_section="Lunch")
        self.assertIn(["custom_combined_section", "like", "%Lunch%"], _build_item_filters())

    def test_item_filters_are_passed_through(self):
        frappe.local.form_dict = frappe._dict(
            item_filters='[["custom_is_website_item", "=", "1"]]'
        )
        self.assertIn(["custom_is_website_item", "=", "1"], _build_item_filters())


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
    def test_item_query_is_distinct(self, visible):
        from excel_restaurant_pos.api.item_group.get_item_group_list import _candidate_group_names

        visible.side_effect = lambda names: names
        with patch(
            "excel_restaurant_pos.api.item_group.get_item_group_list.frappe.get_all",
            return_value=["Beverages"],
        ) as get_all:
            _candidate_group_names()

        self.assertTrue(get_all.call_args.kwargs["distinct"])
        self.assertEqual(get_all.call_args.kwargs["pluck"], "item_group")
        # DISTINCT on item_group plus the default ORDER BY modified is what
        # MySQL rejects under ONLY_FULL_GROUP_BY.
        self.assertIsNone(get_all.call_args.kwargs["order_by"])
