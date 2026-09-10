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
    get_item_list,
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


class TestSearchEndToEnd(FrappeTestCase):
    """The search parameter against real rows, through the real endpoint.

    Everything here is about the seams the unit tests stub out: that the
    ranking survives the fetch, that pagination slices it correctly, and that
    a misspelling cannot reach a row the business filters exclude.
    """

    GROUP = "_Test Search Group"
    HIDDEN_GROUP = "_Test Hidden Search Group"
    ITEMS = [
        ("_Test Biryani", GROUP),
        ("_Test Veg Biryani", GROUP),
        ("_Test Paneer Makhani", GROUP),
        ("_Test Garlic Naan", GROUP),
    ]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for group, till_date in ((cls.GROUP, None), (cls.HIDDEN_GROUP, "2020-01-01")):
            if not frappe.db.exists("Item Group", group):
                frappe.get_doc(
                    {
                        "doctype": "Item Group",
                        "item_group_name": group,
                        "parent_item_group": "All Item Groups",
                        "is_group": 0,
                        "custom_visibility_till_date": till_date,
                    }
                ).insert(ignore_permissions=True)

        for item_code, group in cls.ITEMS:
            cls._make_item(item_code, group)

        # Reachable only by a typo, and disabled -- the fuzzy stage proposes it
        # and the filters have to be what rejects it.
        cls._make_item("_Test Biryani Disabled", cls.GROUP, disabled=1)
        # Same, but excluded by the item group visibility window instead.
        cls._make_item("_Test Biryani Hidden", cls.HIDDEN_GROUP)
        # Nothing in its name or code says so; only the description does.
        cls._make_item(
            "_Test Kulfi",
            cls.GROUP,
            description="A frozen dessert served after a _Test Biryani",
        )

        cls._clear_caches()

    @staticmethod
    def _make_item(item_code, item_group, disabled=0, description=None):
        if frappe.db.exists("Item", item_code):
            return
        frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": item_code,
                "item_name": item_code,
                "item_group": item_group,
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "disabled": disabled,
                # Both are made mandatory on Item by excel_erpnext.
                "has_excel_serials": "No",
                "description": description or item_code,
            }
        ).insert(ignore_permissions=True)

    @staticmethod
    def _clear_caches():
        from excel_restaurant_pos.api.item.search import clear_item_search_index
        from excel_restaurant_pos.api.item_group import clear_visible_item_group_cache

        clear_item_search_index()
        clear_visible_item_group_cache()

    def setUp(self):
        # Redis outlives the per-class rollback, so neither cache can be
        # assumed clean just because the rows are.
        self._clear_caches()
        frappe.local.form_dict = frappe._dict(cmd="api.items.list")

    def call(self, **params):
        # A fresh form_dict per call, or a parameter from the previous one
        # leaks into the next and quietly changes what is being asserted.
        frappe.local.form_dict = frappe._dict(cmd="api.items.list", **params)
        return get_item_list()

    def names(self, response):
        # With no `fields` given, get_all returns `name` and nothing else --
        # which for Item is the item code.
        return [item.get("name") for item in response["items"]]

    def test_a_typo_finds_the_item(self):
        response = self.call(search="biryani", limit_page_length=20)
        self.assertIn("_Test Biryani", self.names(response))

        for query in ("birani", "biryni", "birynai"):
            with self.subTest(query=query):
                self.assertIn("_Test Biryani", self.names(self.call(search=query, limit_page_length=20)))

    def test_the_exact_spelling_still_ranks_first(self):
        response = self.call(search="_Test Paneer Makhani", limit_page_length=20)
        self.assertEqual(self.names(response)[0], "_Test Paneer Makhani")

    def test_a_disabled_item_is_unreachable_by_typo(self):
        # It is in the term index and one edit away, so only the filters stop it.
        for query in ("biryani", "birani", "biryani disabled"):
            with self.subTest(query=query):
                self.assertNotIn(
                    "_Test Biryani Disabled",
                    self.names(self.call(search=query, limit_page_length=500)),
                )

    def test_a_hidden_item_group_is_unreachable_by_typo(self):
        for query in ("biryani", "birani", "biryani hidden"):
            with self.subTest(query=query):
                self.assertNotIn(
                    "_Test Biryani Hidden",
                    self.names(self.call(search=query, limit_page_length=500)),
                )

    def test_search_combines_with_an_explicit_filter(self):
        response = self.call(
            search="biryani",
            filters=frappe.as_json([["item_group", "=", self.HIDDEN_GROUP]]),
            limit_page_length=20,
        )
        self.assertEqual(self.names(response), [])

    def test_pagination_slices_the_ranking(self):
        everything = self.call(search="test", limit_page_length=500)
        total = everything["total_count"]
        self.assertGreaterEqual(total, len(self.ITEMS))

        first = self.call(search="test", limit_page_length=2, limit_start=0)
        second = self.call(search="test", limit_page_length=2, limit_start=2)

        self.assertEqual(first["total_count"], total)
        self.assertEqual(second["total_count"], total)
        self.assertEqual(self.names(first), self.names(everything)[:2])
        self.assertEqual(self.names(second), self.names(everything)[2:4])
        self.assertEqual(set(self.names(first)) & set(self.names(second)), set())
        self.assertTrue(first["has_more"])

    def test_paging_past_the_end_is_empty_but_still_counted(self):
        response = self.call(search="biryani", limit_start=9999, limit_page_length=10)

        self.assertEqual(response["items"], [])
        self.assertGreater(response["total_count"], 0)
        self.assertFalse(response["has_more"])

    def test_a_query_that_matches_nothing(self):
        response = self.call(search="zzzznotathing", limit_page_length=10)

        self.assertEqual(response["items"], [])
        self.assertEqual(response["total_count"], 0)
        self.assertFalse(response["has_more"])

    def test_q_is_accepted_as_an_alias(self):
        self.assertEqual(
            self.names(self.call(q="biryani", limit_page_length=20)),
            self.names(self.call(search="biryani", limit_page_length=20)),
        )

    def test_omitting_search_leaves_the_endpoint_alone(self):
        response = self.call(limit_page_length=5)

        self.assertEqual(len(response["items"]), 5)
        self.assertGreater(response["total_count"], len(self.ITEMS))
        self.assertTrue(response["has_more"])

    def test_the_response_shape_is_unchanged(self):
        searched = self.call(search="biryani", limit_page_length=5)
        plain = self.call(limit_page_length=5)

        self.assertEqual(set(searched), set(plain))
        self.assertEqual(set(searched["items"][0]), set(plain["items"][0]))
        self.assertIn("prices", searched["items"][0])

    def test_a_fields_list_without_name_comes_back_without_name(self):
        response = self.call(
            search="biryani",
            fields=frappe.as_json(["item_code", "item_name"]),
            limit_page_length=5,
        )

        self.assertTrue(response["items"])
        for item in response["items"]:
            self.assertNotIn("name", item)
            self.assertIn("item_code", item)

    def test_the_description_is_searched_but_ranks_last(self):
        ranked = self.names(self.call(search="biryani", limit_page_length=500))

        self.assertIn("_Test Kulfi", ranked)
        self.assertLess(ranked.index("_Test Biryani"), ranked.index("_Test Kulfi"))
        self.assertLess(ranked.index("_Test Veg Biryani"), ranked.index("_Test Kulfi"))
