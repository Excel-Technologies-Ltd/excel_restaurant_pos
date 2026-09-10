# Item search (`api.items.list`)

Typo tolerant, ranked search over the existing item list endpoint. It is one
optional parameter on the endpoint the storefront and POS already call; nothing
about the request or the response changes when it is absent.

- Endpoint: `POST|GET /api/method/api.items.list`
- Code: `excel_restaurant_pos/api/item/search.py`, wired in at
  `excel_restaurant_pos/api/item/get_item_list.py`
- Guest reachable, exactly as before.
- Client-side integration:
  [`item-search-frontend-guide.md`](./item-search-frontend-guide.md).

## Request

Everything the endpoint already accepted still works. One parameter is new:

| Parameter | Type | Notes |
| --- | --- | --- |
| `search` | string | Optional. Turns on ranked search. `q` is accepted as an alias. |

It combines with `filters`, `custom_is_gift_card_item`, `fields`, `limit_start`
and `limit_page_length` as usual.

```
/api/method/api.items.list?search=biryani&limit_page_length=10
/api/method/api.items.list?q=chikn&filters=[["item_group","=","Biryani %26 Classics"]]
```

Two behaviours are worth knowing:

- **Relevance is the sort order.** When `search` is given, results come back
  best match first, which replaces the default `creation desc, item_code asc`
  for that request. No existing caller is affected, because no existing caller
  sends `search`.
- **A query that normalizes to nothing is not a search.** `search=!!!` returns
  the ordinary unfiltered list rather than an empty one.

## Response

Unchanged in shape:

```json
{
  "items": [ { "name": "Biryani", "prices": [...] } ],
  "total_count": 17,
  "has_more": true,
  "limit_start": 0,
  "limit_page_length": 10
}
```

`total_count` is the number of matches, so `has_more` and paging work the same
way they do without a search. It stays identical across every page of the same
query.

If you pass a `fields` list that does not include `name`, the response still
will not include it — the ranking needs it internally and it is removed again
before the rows are returned.

## What the search understands

| Query | Finds | Why |
| --- | --- | --- |
| `biryani` | Biryani | exact |
| `bir`, `biry` | Biryani | prefix |
| `tikki` | Aloo Tikki Chaat | a word of the name |
| `chaat` | Aloo Tikki Chaat-GRE-S | hyphens read as word breaks |
| `biriya`, `biriyani` | Lamb Biriyani, Biryani | one edit |
| `briyani` | Biryani | one transposition |
| `ber`, `bur` | Biryani | one substitution |
| `chikn` | BOGO Chiken Biryani | one edit, in the item's own spelling |
| `burgers` | every burger | the item group matched |
| `xylophone` | nothing | below the threshold |

Ranking, best first:

1. exact match
2. prefix of the name
3. a whole word of the name starting with the query
4. one edit away from the start of the name or one of its words
5. the query buried mid word (`ber` inside `cucumber`)
6. two edits away
7. matched on the description only

Matching on `item_group` costs three tiers, so a word of a product's **name**
always beats a prefix of its **category**. Between two otherwise equal matches
the shorter name wins, because the query covered more of it.

### Short queries

| Length | Behaviour |
| --- | --- |
| 1 | prefix only, on name/code/group |
| 2 | adds substring matching, still no guessing |
| 3–5 | adds one edit of tolerance |
| 6+ | two edits |

A single character never guesses, or `b` would return a third of the menu.

### Normalization

Case, accents and punctuation are folded; digits and word order are kept.
`" Biriyani "`, `"BIRIYANI"` and `"biriyani"` are the same query, and
`Aloo Tikki Chaat-GRE-S` indexes as `aloo tikki chaat gre s` so the variant
suffix behaves like the separate words it is.

Because a normalized query is only word characters and single spaces, no `%` or
`_` can survive into a `LIKE`; nothing downstream has to escape wildcards.

## How it works

Two stages, cheap one first.

**Stage 1 — SQL.** `LIKE` across `item_name`, `item_code`, `item_group` and
`description`, passed as `or_filters` alongside the caller's own filters.
Frappe appends `or_filters` as a single parenthesised group
(`frappe/model/db_query.py:291`), so the query is
`(business filters) AND (search branches)` — a search can never widen past
`disabled`, `variant_of` or the item group visibility window.

**Stage 2 — fuzzy, only when stage 1 found fewer than 10 rows.** It scores the
query against a cached term index — item name, code and group, no descriptions
and no documents — and hands the winning **names** back through SQL under the
same filters. So the fuzzy stage only ever *proposes*; the database still
decides what the caller may see.

The algorithm is prefix anchored Damerau-Levenshtein: the tail of the candidate
is free, because search-as-you-type never has the whole word yet, and a
transposition costs one edit rather than two. That single measure is what makes
every case in the table above work.

### Why not a database feature

- **`pg_trgm` / trigram similarity.** Not applicable — this is MariaDB. It would
  not help anyway: `word_similarity('ber','biryani')` is about 0.11, far below
  any usable threshold. Trigram similarity fundamentally cannot get `ber` to
  `Biryani`.
- **MariaDB `FULLTEXT`.** No ngram parser (that is MySQL only), a default
  minimum token length of 3, and no notion of edit distance. It cannot do
  autocomplete or typos.
- **`SOUNDEX`.** `SOUNDEX('bir')` is `B600`, `SOUNDEX('Biryani')` is `B650` —
  they do not even match, and it is word level so it cannot do prefixes.

### Indexes

**None were added, deliberately.** No MariaDB index accelerates `LIKE '%x%'` or
edit distance. The prefix path already uses the existing indexes on
`tabItem.item_name` (BTREE) and `tabItem.item_code` (unique); `name` is the
primary key, which is what stage 2's `name in (...)` lookup uses. The only
index that could theoretically apply is `FULLTEXT`, which cannot satisfy the
requirement. Adding one would cost writes and buy nothing.

### Caching

The term index lives in Redis under `arcpos:item_search_index` for 300s, and is
cleared on any Item insert, update or delete
(`excel_restaurant_pos/doc_event/item/clear_search_index.py`), so a menu edit
shows up in search immediately rather than up to five minutes later.

## Measurements

Taken on the development site: 262 items, 142 searchable, index 142 entries /
52 KB.

| | best | avg |
| --- | --- | --- |
| index build (cache miss) | 1.3 ms | 1.4 ms |
| index read (cache hit) | 0.08 ms | 0.08 ms |
| correctly spelled query (stage 1 only) | 1.1 ms | 1.2 ms |
| typo (stage 1 + stage 2) | 3.2 ms | 3.4 ms |
| fetch every item and score it in Python | 9.7 ms | 9.9 ms |

The last row is the approach this design exists to avoid. It is slower even on
a catalogue this small, and the gap is structural rather than incidental: it
re-fetches every row including the HTML description and re-normalizes every
field **on every request**, where stage 2 reads a pre-normalized, three-field,
description-free index out of Redis and only runs at all when spelling failed.

### Where this stops scaling

Stage 2 is linear in catalogue size. Measured against a synthetic index:

| entries | stage 2 |
| --- | --- |
| 142 | 1.8 ms |
| 1,000 | 12.8 ms |
| 10,000 | 128 ms |
| 50,000 | 656 ms |

Stage 1 is unaffected, so correctly spelled queries stay fast at any size — but
past roughly 10,000 items the fallback becomes too slow for a search box. A
restaurant menu is bounded by what a kitchen can cook, so this is not a near
term concern here. If a catalogue ever gets there, the fix is to move stage 2
out of Python rather than to tune it: a dedicated search index (Typesense,
Meilisearch, OpenSearch) doing exactly what stage 2 does now, with stage 1 and
the re-query through SQL left as they are.

`CANDIDATE_LIMIT` (500) caps how many rows stage 1 will rank at once, for the
same reason: beyond it, relevance would start depending on the order MariaDB
happened to return rows in.
