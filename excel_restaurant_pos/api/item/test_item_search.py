# Copyright (c) 2026, Excel and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.item.search import (
    CANDIDATE_LIMIT,
    FUZZY_TRIGGER_COUNT,
    PREFIX_ONLY_FIELDS,
    SEARCH_FIELDS,
    build_match_filters,
    find_ranked_names,
    max_distance,
    normalize,
    prefix_distance,
)

MODULE = "excel_restaurant_pos.api.item.search"

# The dish on its own, which is the world the requirement's example table is
# written against: every listed spelling has to reach it and nothing competes.
SOLO_MENU = [
    ("Biriyani", "Main Course"),
    ("Rice", "Main Course"),
    ("Aloo Gobi", "Main Course"),
    ("Paneer Makhani", "Main Course"),
]

# The requirement's ranking example, which adds products that are genuinely
# better literal matches for some of those same queries.
RANKING_MENU = [
    ("Biriyani", "Rice Dishes"),
    ("Biryani Masala", "Spice Mixes"),
    ("Chicken Burger", "Burgers"),
    ("Beef Burger", "Burgers"),
    ("Rice", "Rice Dishes"),
    ("Aloo Tikki Chaat-GRE-S", "Indian Street Starters"),
]


def _index(menu):
    """The cached term index, shaped the way _build_search_index leaves it."""
    entries = []
    for item_name, item_group in menu:
        fields = []
        for fieldname, raw in (
            ("item_name", item_name),
            ("item_code", item_name),
            ("item_group", item_group),
        ):
            value = normalize(raw)
            if value:
                fields.append((fieldname, value, tuple(value.split())))
        entries.append({"name": item_name, "fields": fields, "length": len(item_name)})

    return entries


def _fake_sql(menu):
    """Stand in for MariaDB: literal LIKE matching over the raw columns.

    Whatever this returns has, by definition, already cleared the caller's
    filters -- which is exactly the contract the real _match_names has.
    """

    def match(filters, or_filters):
        if or_filters and or_filters[0][0] == "name":
            wanted = set(or_filters[0][2])
            return [name for name, _group in menu if name in wanted]

        found = []
        for item_name, item_group in menu:
            columns = {
                "item_name": item_name.lower(),
                "item_code": item_name.lower(),
                "item_group": item_group.lower(),
                "description": "",
            }
            for fieldname, _operator, pattern in or_filters:
                value = columns[fieldname]
                needle = pattern.strip("%")
                if pattern.startswith("%"):
                    hit = needle in value
                else:
                    hit = value.startswith(needle)
                if hit:
                    found.append(item_name)
                    break

        return found

    return match


class _SearchCase(FrappeTestCase):
    menu = SOLO_MENU

    def setUp(self):
        index = patch(f"{MODULE}.get_search_index", return_value=_index(self.menu))
        index.start()
        self.addCleanup(index.stop)

        sql = patch(f"{MODULE}._match_names", side_effect=_fake_sql(self.menu))
        sql.start()
        self.addCleanup(sql.stop)

    def search(self, term):
        return find_ranked_names(term, [])


class TestNormalize(FrappeTestCase):
    def test_case_and_surrounding_whitespace(self):
        for raw in (" Biriyani ", "BIRIYANI", "biriyani", "  BiRiYaNi\t"):
            self.assertEqual(normalize(raw), "biriyani")

    def test_repeated_spaces_collapse(self):
        self.assertEqual(normalize("Chicken    Burger"), "chicken burger")

    def test_punctuation_becomes_a_word_break(self):
        # Variant suffixes are hyphenated, so a hyphen has to read as the space
        # it stands in for or "chaat" would never be a token of its own.
        self.assertEqual(normalize("Aloo Tikki Chaat-GRE-S"), "aloo tikki chaat gre s")

    def test_digits_survive(self):
        self.assertEqual(normalize("Aloo Chop - 4 Pcs"), "aloo chop 4 pcs")

    def test_accents_fold(self):
        self.assertEqual(normalize("Crème Brûlée"), "creme brulee")

    def test_empty_and_punctuation_only(self):
        for raw in (None, "", "   ", "!!!", "%%"):
            self.assertEqual(normalize(raw), "")

    def test_like_wildcards_cannot_survive(self):
        """Nothing escapes LIKE downstream because nothing needs to."""
        self.assertEqual(normalize("100%_off"), "100 off")


class TestPrefixDistance(FrappeTestCase):
    """Search as you type never has the whole word, so the tail stays free."""

    def test_a_prefix_costs_nothing(self):
        self.assertEqual(prefix_distance("bir", "biryani", 2), 0)

    def test_one_substitution(self):
        self.assertEqual(prefix_distance("ber", "biryani", 1), 1)
        self.assertEqual(prefix_distance("bur", "biryani", 1), 1)

    def test_one_deletion(self):
        # "biriya" is "birya" with an extra i, and "birya" starts "biryani".
        self.assertEqual(prefix_distance("biriya", "biryani", 2), 1)

    def test_one_transposition_counts_once(self):
        # Plain Levenshtein would call this two substitutions.
        self.assertEqual(prefix_distance("briyani", "biryani", 2), 1)

    def test_a_missing_character(self):
        self.assertEqual(prefix_distance("biryani", "biriyani", 2), 1)

    def test_an_extra_character(self):
        self.assertEqual(prefix_distance("biriyani", "biryani", 2), 1)

    def test_over_the_limit_reports_one_past_it(self):
        self.assertEqual(prefix_distance("rice", "biryani", 1), 2)

    def test_the_limit_is_never_exceeded_in_the_return(self):
        self.assertEqual(prefix_distance("completely different", "rice", 2), 3)

    def test_an_empty_query_matches_anything(self):
        self.assertEqual(prefix_distance("", "biryani", 1), 0)

    def test_an_empty_candidate(self):
        self.assertEqual(prefix_distance("bir", "", 1), 2)


class TestMaxDistance(FrappeTestCase):
    def test_under_three_characters_is_never_guessed_at(self):
        for query in ("", "b", "bi"):
            self.assertEqual(max_distance(query), 0)

    def test_short_queries_get_one_edit(self):
        for query in ("bir", "biry", "birya"):
            self.assertEqual(max_distance(query), 1)

    def test_longer_queries_get_two(self):
        for query in ("biriya", "briyani", "biriyani"):
            self.assertEqual(max_distance(query), 2)


class TestMatchFilters(FrappeTestCase):
    def test_a_single_character_stays_a_prefix(self):
        filters = build_match_filters("b")
        self.assertEqual([row[0] for row in filters], list(PREFIX_ONLY_FIELDS))
        self.assertTrue(all(row[2] == "b%" for row in filters))

    def test_two_characters_open_up_to_substrings(self):
        filters = build_match_filters("bi")
        self.assertEqual([row[0] for row in filters], list(SEARCH_FIELDS))
        self.assertTrue(all(row[2] == "%bi%" for row in filters))

    def test_description_is_only_ever_a_substring_field(self):
        self.assertNotIn("description", PREFIX_ONLY_FIELDS)
        self.assertIn("description", SEARCH_FIELDS)


class TestTheRequiredSpellings(_SearchCase):
    """The eight queries the requirement names, against the dish on its own."""

    menu = SOLO_MENU

    def test_every_spelling_finds_the_dish(self):
        for query in ("bir", "biry", "biriya", "biriyani", "biryani", "briyani", "ber", "bur"):
            with self.subTest(query=query):
                self.assertEqual(
                    self.search(query)[0], "Biriyani", f"{query!r} did not find Biriyani"
                )

    def test_case_and_whitespace_do_not_change_the_answer(self):
        self.assertEqual(self.search("  BIRIYANI  "), self.search("biriyani"))

    def test_a_typo_does_not_drag_back_the_rest_of_the_menu(self):
        for query in ("ber", "bur", "briyani"):
            with self.subTest(query=query):
                self.assertEqual(self.search(query), ["Biriyani"])

    def test_an_unrelated_query_returns_nothing(self):
        for query in ("xylophone", "zzzz", "qqq"):
            self.assertEqual(self.search(query), [])


class TestRanking(_SearchCase):
    """The requirement's own ranking example, competitors included."""

    menu = RANKING_MENU

    def test_a_prefix_beats_a_longer_prefix(self):
        # Both start with "bir"; the shorter name is the one the query covered
        # more of, so it is the better guess.
        self.assertEqual(self.search("bir")[0], "Biriyani")

    def test_an_exact_match_comes_first(self):
        self.assertEqual(self.search("rice")[0], "Rice")

    def test_a_word_of_the_name_beats_a_typo(self):
        # "bur" starts the word "Burger", which is a real match; reading it as
        # "Biriyani" is a guess, and a guess never outranks a hit.
        ranked = self.search("bur")
        self.assertEqual(ranked[:2], ["Beef Burger", "Chicken Burger"])
        self.assertIn("Biriyani", ranked)

    def test_a_typo_beats_a_match_buried_mid_word(self):
        # "ber" is one edit from "Biriyani" but sits inside "burger".
        ranked = self.search("ber")
        self.assertEqual(ranked[0], "Biriyani")

    def test_a_word_of_the_name_beats_a_prefix_of_the_category(self):
        # Everything in "Rice Dishes" starts with the query too. The name wins.
        ranked = self.search("rice")
        self.assertLess(ranked.index("Rice"), ranked.index("Biriyani"))

    def test_a_category_still_finds_its_items(self):
        ranked = self.search("burgers")
        self.assertIn("Chicken Burger", ranked)
        self.assertIn("Beef Burger", ranked)

    def test_a_token_in_the_middle_of_a_name_is_found(self):
        self.assertIn("Aloo Tikki Chaat-GRE-S", self.search("tikki"))

    def test_a_hyphenated_variant_suffix_is_a_token(self):
        self.assertIn("Aloo Tikki Chaat-GRE-S", self.search("chaat"))

    def test_a_single_character_is_prefix_only(self):
        # "Rice Dishes" starts with r, so Biriyani comes along as a category
        # match -- but nothing arrives on a letter buried mid-word.
        ranked = self.search("r")
        self.assertEqual(ranked[0], "Rice")
        self.assertNotIn("Chicken Burger", ranked)

    def test_two_characters_are_not_guessed_at(self):
        # "bu" reaches the burgers literally; it must not become "bi".
        self.assertNotIn("Biriyani", self.search("bu"))

    def test_an_empty_query_is_not_a_search(self):
        for term in ("", "   ", "!!!"):
            self.assertIsNone(find_ranked_names(term, []))


class TestTheFuzzyStageIsAFallback(FrappeTestCase):
    """It is what happens when spelling fails, not what happens every time."""

    def setUp(self):
        index = patch(f"{MODULE}.get_search_index", return_value=_index(RANKING_MENU))
        index.start()
        self.addCleanup(index.stop)

    @patch(f"{MODULE}._fuzzy_names", return_value=[])
    @patch(f"{MODULE}._match_names")
    def test_a_well_spelled_query_never_scores_in_python(self, match, fuzzy):
        match.return_value = [f"ITEM-{i}" for i in range(FUZZY_TRIGGER_COUNT)]

        find_ranked_names("biryani", [])

        fuzzy.assert_not_called()
        self.assertEqual(match.call_count, 1)

    @patch(f"{MODULE}._fuzzy_names", return_value=["Biriyani"])
    @patch(f"{MODULE}._match_names")
    def test_a_thin_result_falls_back(self, match, fuzzy):
        match.side_effect = [[], ["Biriyani"]]

        self.assertEqual(find_ranked_names("briyani", []), ["Biriyani"])
        fuzzy.assert_called_once()
        # The guesses go back through SQL rather than straight to the caller.
        self.assertEqual(match.call_count, 2)
        self.assertEqual(match.call_args.args[1], [["name", "in", ["Biriyani"]]])

    @patch(f"{MODULE}._fuzzy_names")
    @patch(f"{MODULE}._match_names", return_value=[])
    def test_a_two_character_query_never_falls_back(self, _match, fuzzy):
        find_ranked_names("bi", [])

        fuzzy.assert_not_called()


class TestSearchCannotOutrunTheFilters(FrappeTestCase):
    """A typo must not reach a row the correct spelling could not."""

    def setUp(self):
        index = patch(f"{MODULE}.get_search_index", return_value=_index(RANKING_MENU))
        index.start()
        self.addCleanup(index.stop)

    @patch(f"{MODULE}._fuzzy_names", return_value=["Biriyani"])
    @patch(f"{MODULE}._match_names", return_value=[])
    def test_both_stages_query_under_the_same_filters(self, match, _fuzzy):
        filters = [["disabled", "=", 0], ["item_group", "in", ["Burgers"]]]

        find_ranked_names("briyani", filters)

        self.assertEqual(match.call_count, 2)
        for call in match.call_args_list:
            self.assertEqual(call.args[0], filters)

    @patch(f"{MODULE}._fuzzy_names", return_value=["Biriyani"])
    @patch(f"{MODULE}._match_names", return_value=[])
    def test_a_guess_the_filters_reject_is_dropped(self, _match, _fuzzy):
        # The second _match_names returns nothing either, i.e. the filters
        # excluded the guess. It must not appear in the result regardless.
        self.assertEqual(find_ranked_names("briyani", []), [])


class TestCandidateCap(FrappeTestCase):
    def test_the_fallback_triggers_well_below_the_cap(self):
        self.assertGreaterEqual(CANDIDATE_LIMIT, 500)
        self.assertLess(FUZZY_TRIGGER_COUNT, CANDIDATE_LIMIT)
