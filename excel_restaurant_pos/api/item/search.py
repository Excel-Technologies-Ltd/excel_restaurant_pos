"""Typo tolerant item search for the storefront and POS item list.

The endpoint behind this is api.items.list, which serves a restaurant menu: a
few hundred short names, and a search box that fires on every keystroke. Two
stages keep that cheap.

Stage 1 runs entirely in SQL -- exact, prefix and substring LIKE across the
searchable Item fields, under the caller's own filters. It answers every query
that is a real fragment of a product name ("bir", "biry", "biriya"), which is
almost all of them, in one round trip.

Stage 2 only runs when stage 1 came back nearly empty, which is what a typo
looks like ("ber", "briyani"). It scores the query against
a compact cached term index -- item code, name and group, no descriptions and
no documents -- and hands the winning *names* back to SQL. The caller's filters
and the item group visibility window are applied there, so a misspelling can
never reach a row that the correct spelling could not.

MariaDB has nothing to offer for stage 2. Its InnoDB full text index has no
ngram parser (that is MySQL only) and no notion of edit distance, and SOUNDEX
is word level, so no amount of indexing would let "ber" find "Biryani" in the
database itself.
"""

import re
import unicodedata

import frappe

ITEM_DOCTYPE = "Item"

SEARCH_INDEX_CACHE_KEY = "arcpos:item_search_index"
SEARCH_INDEX_TTL = 300

# The widest net stage 1 casts. Ranking needs every candidate in hand at once,
# so this is also the point past which relevance would start depending on the
# order MariaDB happened to return rows in. A restaurant menu is nowhere near
# it -- docs/item-search-api.md records the measurements and what to reach for
# if a catalogue ever outgrows this.
CANDIDATE_LIMIT = 500

# Stage 2 runs when stage 1 found fewer rows than this. Deliberately a constant
# rather than the requested page size: it keeps total_count identical on every
# page of the same search, which paging through a growing total would not.
FUZZY_TRIGGER_COUNT = 10

# One character is a keystroke, not a word -- matching it anywhere drags back a
# third of the menu, so it stays a prefix. Two is still too little to tell a
# typo from a genuinely different product.
MIN_SUBSTRING_LENGTH = 2
MIN_FUZZY_LENGTH = 3

# Fields stage 1 matches, best first. `description` is one of the Item DocType's
# own search_fields but it is stored as HTML, so it only ever earns the lowest
# tier and is never guessed at.
SEARCH_FIELDS = ("item_name", "item_code", "item_group", "description")
PREFIX_ONLY_FIELDS = ("item_name", "item_code", "item_group")
FIELD_RANK = {field: rank for rank, field in enumerate(SEARCH_FIELDS)}

# Only the two identity fields are guessed at. Fuzzy matching a category or a
# description is how a search box starts returning the whole menu.
INDEX_FIELDS = ("item_name", "item_code", "item_group")
FUZZY_FIELDS = ("item_name", "item_code")

# Match quality, best first. A near miss on the start of a word beats a literal
# match buried in the middle of one: "ber" meaning "Biryani" is a better guess
# than "ber" meaning "CucumBER Salad". UNRANKED is for a row SQL matched on
# something the index does not carry -- a word in the description -- which is a
# real match but the weakest kind.
EXACT, PREFIX, TOKEN_PREFIX, NEAR, SUBSTRING, LOOSE, UNRANKED = range(7)

# Matching in a weaker field costs tiers outright, not just a tiebreak. Without
# this, a prefix of the *category* would outrank a word of the *name*: every
# item in "Biryani & Classics" -- Beef Bhuna, Beef Tehari -- crowded out "Veg
# Biryani" for the query "biry".
FIELD_PENALTY = {"item_name": 0, "item_code": 0, "item_group": 3}

_NON_WORD = re.compile(r"[^\w\s]|_", re.UNICODE)


def normalize(text) -> str:
    """Fold case, accents and punctuation; keep digits and word order.

    "Aloo Tikki Chaat-GRE-S" becomes "aloo tikki chaat gre s", so the hyphens
    that separate a variant suffix behave like the spaces they stand in for.

    This also happens to be why nothing downstream escapes LIKE wildcards: a
    normalized query is word characters and single spaces, so neither `%` nor
    `_` can survive to reach the database as a wildcard.
    """
    if not text:
        return ""

    decomposed = unicodedata.normalize("NFKD", str(text))
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(_NON_WORD.sub(" ", unaccented).casefold().split())


def max_distance(query: str) -> int:
    """How many edits a query of this length is allowed to be wrong by.

    Short queries get one edit because that is all the required cases need --
    "ber" is one substitution from "bir" -- and because a second edit on three
    characters matches almost anything. Six characters is enough context that
    two edits still describe the same word: "biriyani" for "biryani".
    """
    if len(query) < MIN_FUZZY_LENGTH:
        return 0
    return 1 if len(query) < 6 else 2


def prefix_distance(query: str, candidate: str, limit: int) -> int:
    """Edit distance from `query` to the closest prefix of `candidate`.

    Search-as-you-type never has the whole word yet, so the tail of the
    candidate has to be free: "biriya" is one deletion from the start of
    "biryani", even though the two complete strings are three edits apart.

    Transpositions cost one edit, not two, which is what makes "briyani" a near
    miss for "biryani" rather than a stranger to it.

    Returns `limit + 1` when nothing that close exists, so the caller can treat
    any value over the limit as "no match" without a second comparison.
    """
    if not query:
        return 0

    # Past this point the candidate can only add characters the query does not
    # have, and each one costs an edit we have already ruled out.
    candidate = candidate[: len(query) + limit]
    if not candidate:
        return min(len(query), limit + 1)

    previous = None
    current = list(range(len(candidate) + 1))

    for i, query_char in enumerate(query, start=1):
        row = [i] + [0] * len(candidate)
        for j, candidate_char in enumerate(candidate, start=1):
            cost = 0 if query_char == candidate_char else 1
            value = min(current[j] + 1, row[j - 1] + 1, current[j - 1] + cost)
            if (
                i > 1
                and j > 1
                and query_char == candidate[j - 2]
                and query[i - 2] == candidate_char
            ):
                value = min(value, previous[j - 2] + 1)
            row[j] = value

        # Every later row is at least as large, so once the whole row is out of
        # reach the answer is settled.
        if min(row) > limit:
            return limit + 1

        previous, current = current, row

    # The prefix is free to end anywhere, so the best cell in the last row wins.
    return min(min(current), limit + 1)


def _score_field(query, value, tokens, allow_substring, distance_limit):
    """Best (tier, distance) this one field earns, or None if it does not match."""
    if not value:
        return None

    if value == query:
        return EXACT, 0
    if value.startswith(query):
        return PREFIX, 0
    for token in tokens:
        if token.startswith(query):
            return TOKEN_PREFIX, 0
    if allow_substring and query in value:
        return SUBSTRING, 0
    if not distance_limit:
        return None

    best = distance_limit + 1
    for text in (value, *tokens):
        best = min(best, prefix_distance(query, text, distance_limit))
        if best <= 1:
            break

    if best > distance_limit:
        return None
    return (NEAR if best <= 1 else LOOSE), best


def _build_search_index():
    """The term index: one small row per item, nothing a page would render.

    Built from the same population the endpoint always filters to, so it is a
    superset of any single request and does not need rebuilding when a caller
    passes different filters. Visibility windows are deliberately left out --
    this only proposes names, and SQL decides which of them the caller may see.
    """
    rows = frappe.get_all(
        ITEM_DOCTYPE,
        filters={"disabled": 0, "variant_of": ("is", "not set")},
        fields=["name", *INDEX_FIELDS],
        limit_page_length=0,
    )

    index = []
    for row in rows:
        fields = []
        for fieldname in INDEX_FIELDS:
            value = normalize(row.get(fieldname))
            if value:
                fields.append((fieldname, value, tuple(value.split())))

        if fields:
            index.append(
                {
                    "name": row.name,
                    "fields": fields,
                    "length": len(row.get("item_name") or row.name),
                }
            )

    return index


def get_search_index():
    cache = frappe.cache()
    # `expires=True` or the miss is served from frappe.local for the rest of the
    # request while set_value(expires_in_sec=...) writes only to redis.
    index = cache.get_value(SEARCH_INDEX_CACHE_KEY, expires=True)
    if index is None:
        index = _build_search_index()
        cache.set_value(SEARCH_INDEX_CACHE_KEY, index, expires_in_sec=SEARCH_INDEX_TTL)

    return index


def clear_item_search_index():
    frappe.cache().delete_value(SEARCH_INDEX_CACHE_KEY)


def build_match_filters(query: str):
    """LIKE branches for stage 1, shaped as `or_filters` for frappe.get_all.

    Frappe ANDs these onto the caller's filters as one parenthesised group, so
    nothing here can widen past `disabled`, `variant_of` or the visible item
    groups.
    """
    if len(query) < MIN_SUBSTRING_LENGTH:
        return [[fieldname, "like", f"{query}%"] for fieldname in PREFIX_ONLY_FIELDS]

    # `%q%` already covers `q%`, so a separate prefix branch would only cost a
    # second scan for the same rows.
    return [[fieldname, "like", f"%{query}%"] for fieldname in SEARCH_FIELDS]


def _match_names(filters, or_filters):
    return frappe.get_all(
        ITEM_DOCTYPE,
        filters=filters,
        or_filters=or_filters,
        pluck="name",
        order_by="item_name asc",
        limit_page_length=CANDIDATE_LIMIT,
    )


def _fuzzy_names(query, exclude):
    """Names the database could not reach by spelling, scored against the index."""
    limit = max_distance(query)
    if not limit:
        return []

    names = []
    for entry in get_search_index():
        if entry["name"] in exclude:
            continue

        for fieldname, value, tokens in entry["fields"]:
            if fieldname not in FUZZY_FIELDS:
                continue
            if _score_field(query, value, tokens, True, limit):
                names.append(entry["name"])
                break

        if len(names) >= CANDIDATE_LIMIT:
            break

    return names


def _rank(query, names):
    index = {entry["name"]: entry for entry in get_search_index()}
    limit = max_distance(query)
    allow_substring = len(query) >= MIN_SUBSTRING_LENGTH

    ranked = []
    for position, name in enumerate(names):
        entry = index.get(name)
        best = (UNRANKED, len(SEARCH_FIELDS), 0)
        length = 0

        if entry:
            length = entry["length"]
            for fieldname, value, tokens in entry["fields"]:
                scored = _score_field(
                    query,
                    value,
                    tokens,
                    allow_substring,
                    limit if fieldname in FUZZY_FIELDS else 0,
                )
                if scored:
                    tier = min(scored[0] + FIELD_PENALTY[fieldname], UNRANKED)
                    best = min(best, (tier, FIELD_RANK[fieldname], scored[1]))

        # A shorter name means the query covered more of it, which is the better
        # guess between two otherwise equal matches: "Biryani" over
        # "Biryani-Hyderabadi Biryani-L". `position` keeps the rest stable.
        ranked.append((*best, length, position, name))

    ranked.sort()
    return [row[-1] for row in ranked]


def find_ranked_names(search_term, filters):
    """Item names matching `search_term`, most relevant first.

    Returns None when the term normalizes away to nothing, which the caller
    should treat as no search at all rather than as a search that matched
    nothing.
    """
    query = normalize(search_term)
    if not query:
        return None

    names = _match_names(filters, build_match_filters(query))

    if len(names) < FUZZY_TRIGGER_COUNT and len(query) >= MIN_FUZZY_LENGTH:
        guesses = _fuzzy_names(query, exclude=set(names))
        if guesses:
            # Back through SQL under the same filters: the index knows nothing
            # about visibility windows or whatever else the caller asked for.
            names = names + _match_names(filters, [["name", "in", guesses]])

    return _rank(query, names)
