# Item Search — Frontend Integration Guide

How the storefront and POS wire a typo-tolerant search box to the item list.

**Audience:** frontend developers on the storefront / POS SPA.
**Backend reference:** [`item-search-api.md`](./item-search-api.md).

---

## 1. The one thing to understand first

**There is no new endpoint.** Search is one optional parameter on the item list
call you already make:

```diff
  GET /api/method/api.items.list?limit_page_length=20
+ GET /api/method/api.items.list?limit_page_length=20&search=biryani
```

Everything else — `filters`, `fields`, `limit_start`, `limit_page_length`,
`custom_is_gift_card_item`, the response shape — is unchanged. If you already
render the item list, you already have 90% of this.

Two consequences worth internalising before you write any code:

- **An empty or meaningless query is not an empty result.** `search=`,
  `search=%20`, and `search=!!!` all return the **ordinary full item list**, not
  zero rows. That is deliberate — punctuation alone is not a search — but it
  means you must not render "No results for `!!!`" when the server just handed
  you the whole menu. Decide client-side whether you are in "search mode"; see
  §5.
- **Relevance replaces your sort order.** When `search` is present, any
  `order_by` you send is ignored and results come back best-match-first. That is
  the point, but do not leave a "Sort by: Newest" control looking active while a
  search is running.

---

## 2. Prerequisites

**Auth.** `api.items.list` is `allow_guest=True`, so an anonymous storefront
works with no token at all. If your SPA already sends
`Authorization: Bearer <accessToken>`, keep sending it — the behaviour is
identical either way.

**CORS.** The API site's `site_config.json` must allow your origin, or the
browser blocks the response before your code runs:

```json
{
  "allow_cors": "https://pos-order.aninda.me"
}
```

**No rate limit.** This endpoint is not rate limited, which means throttling is
*your* responsibility. A search box that fires on every keystroke with no
debounce will issue ~8 requests for "biryani". See §4.

---

## 3. The request

| Parameter | Type | Notes |
|---|---|---|
| `search` | string | **New, optional.** `q` works as an alias. Turns on ranked search. |
| `filters` | JSON array | Unchanged. Combines with `search` (AND). |
| `fields` | JSON array | Unchanged. See the `name` note below. |
| `limit_start` | int | Unchanged. Offset into the **ranked** list. |
| `limit_page_length` | int | Unchanged. 1–500, default 10. |
| `custom_is_gift_card_item` | `0` / `1` | Unchanged. Combines with `search`. |
| `order_by` | string | **Ignored while `search` is set.** |

```ts
const API = import.meta.env.VITE_API_BASE_URL;

export type ItemSearchParams = {
  search?: string;
  filters?: unknown[];
  fields?: string[];
  limitStart?: number;
  limitPageLength?: number;
  giftCardOnly?: boolean;
  signal?: AbortSignal;
};

export async function fetchItems(params: ItemSearchParams) {
  const query = new URLSearchParams({
    limit_start: String(params.limitStart ?? 0),
    limit_page_length: String(params.limitPageLength ?? 20),
  });

  // Only send `search` when there is something to search for. Sending an empty
  // string is harmless but pointless -- it returns the plain list anyway.
  const term = params.search?.trim();
  if (term) query.set("search", term);
  if (params.filters?.length) query.set("filters", JSON.stringify(params.filters));
  if (params.fields?.length) query.set("fields", JSON.stringify(params.fields));
  if (params.giftCardOnly !== undefined) {
    query.set("custom_is_gift_card_item", params.giftCardOnly ? "1" : "0");
  }

  const res = await fetch(`${API}/api/method/api.items.list?${query}`, {
    headers: { Accept: "application/json" },
    signal: params.signal,
  });
  if (!res.ok) throw await toApiError(res);

  return (await res.json()).message as ItemListResponse;
}
```

### The `name` field

With no `fields`, each row is `{ name, prices }` — and for Item, `name` **is**
the item code. If you pass `fields` **without** `name`, the response will not
contain it either; the backend adds it internally to preserve the ranking and
strips it again, so your row shape is exactly what it would be without a search.

If you key your React list on `item.name`, either omit `fields` or include
`"name"` in it explicitly.

---

## 4. Wiring the search box

Two things will bite you: firing per keystroke, and out-of-order responses.

**Out-of-order is the subtle one.** Type `bir` fast and the request for `bi` can
land *after* the request for `bir`, leaving stale results on screen under a
newer query. Debouncing reduces this; it does not fix it. Abort the previous
request and guard on the term.

```ts
export function useItemSearch(term: string, delay = 250) {
  const [state, setState] = useState<{
    items: Item[];
    total: number;
    loading: boolean;
  }>({ items: [], total: 0, loading: false });

  useEffect(() => {
    const query = term.trim();

    // Below the threshold, show the normal list rather than searching. See §6.
    if (query.length < 2) {
      setState({ items: [], total: 0, loading: false });
      return;
    }

    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true }));

    const timer = setTimeout(async () => {
      try {
        const res = await fetchItems({
          search: query,
          limitPageLength: 20,
          signal: controller.signal,
        });
        setState({ items: res.items, total: res.total_count, loading: false });
      } catch (err) {
        // An abort is the expected outcome of typing another character.
        if ((err as Error).name === "AbortError") return;
        setState({ items: [], total: 0, loading: false });
        toast.error((err as Error).message);
      }
    }, delay);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [term, delay]);

  return state;
}
```

`250ms` is a reasonable starting debounce: a typical query costs 1–4 ms server
side, so the round trip is dominated by the network, and the user perceives
anything under ~300 ms as instant.

---

## 5. Search mode vs. browse mode

Because a meaningless query returns the full list, "did I get results?" is not
the right question. Track the mode client-side:

```ts
const query = term.trim();
const isSearching = query.length >= 2;

if (!isSearching) return <ItemGrid items={browseItems} />;
if (loading)      return <Skeleton />;
if (!items.length) return <Empty>No items match “{query}”.</Empty>;
return <ItemGrid items={items} />;
```

A genuinely unmatched query does return `{ items: [], total_count: 0 }` — you
just cannot rely on the *absence* of that to mean "the search worked".

---

## 6. Short queries

The backend deliberately narrows what it does for very short input, because a
single character otherwise matches a third of a menu:

| Length | Backend behaviour | Suggested UI |
|---|---|---|
| 0 | not a search — full list | browse mode |
| 1 | prefix matching only, no typo tolerance | browse mode, or show results but do not call it "search" |
| 2 | adds substring matching, still no guessing | search mode |
| 3–5 | adds one character of typo tolerance | search mode |
| 6+ | two characters of tolerance | search mode |

Starting at **2** is the sane default. One character is a valid request and will
return sensible prefix matches if you want an eager dropdown — it is just noisy
enough that most storefronts should not.

---

## 7. Pagination and infinite scroll

Pagination works exactly as it does without a search — `limit_start` is an
offset into the ranked list:

```ts
// page 1
fetchItems({ search: "bir", limitStart: 0, limitPageLength: 3 });
// → ["Biryani", "Veg Biryani", "Lamb Biriyani"], total_count: 18, has_more: true

// page 2
fetchItems({ search: "bir", limitStart: 3, limitPageLength: 3 });
// → ["Mutton Biryani", "Shrimp Biryani", "Chicken Biryani"], total_count: 18
```

**`total_count` is stable across every page of the same query**, so it is safe
to drive a page count or a "18 results" label from page 1 and not recompute it.

For infinite scroll, reset `limit_start` to `0` whenever the term changes — a
common bug is appending page 2 of `biryani` onto page 1 of `bir`.

---

## 8. What the ranking will do

Best first:

1. exact match
2. prefix of the name
3. a whole word of the name starting with the query
4. one edit away from the start of the name or one of its words
5. the query buried mid-word (`ber` inside `cucumber`)
6. two edits away
7. matched on the description only

A match on the **item group** costs three tiers, so a word of a product's *name*
always outranks a prefix of its *category*. Between two otherwise equal matches
the shorter name wins.

Real results from the development menu:

| Query | Top results |
|---|---|
| `bir` | Biryani, Veg Biryani, Lamb Biriyani |
| `briyani` | Biryani, Veg Biryani, Lamb Biriyani |
| `ber` | Biryani, Beef Bhuna, Burger Bun |
| `chikn` | BOGO Chiken Biryani |
| `burgers` | every item in the Burgers group |
| `xylophone` | *(none)* |

**Do not promise the user a "did you mean X?"** — there is no spelling
suggestion endpoint. The correction is implicit in the results.

**Do highlight matches carefully.** A naive `indexOf(query)` highlighter will
find nothing in `Biryani` for the query `briyani`, because the match was fuzzy.
Either highlight only when the substring genuinely occurs, or skip highlighting.

---

## 9. Combining with filters

`search` ANDs with everything else. Nothing a search returns can escape a filter,
a disabled item, or an item group that is outside its visibility window.

```ts
// Search within one category
fetchItems({ search: "bir", filters: [["item_group", "=", "Biryani & Classics"]] });
// → total_count 16 (vs 18 unfiltered)

// Search only gift card items
fetchItems({ search: "gift", giftCardOnly: true });
// → total_count 1
```

That last property matters: **a typo cannot reach a row that the correct
spelling could not**. You do not need to re-check visibility client-side.

---

## 10. Errors

Same `_server_messages` shape as every other endpoint here:

```ts
export async function toApiError(res: Response) {
  let message = res.statusText;
  try {
    const body = await res.json();
    const serverMessages = JSON.parse(body._server_messages ?? "[]");
    if (serverMessages.length) {
      message = JSON.parse(serverMessages[0]).message ?? message;
    } else if (body.exception) {
      message = String(body.exception);
    }
  } catch {
    // Non-JSON body (a proxy error page, say) — keep the status text.
  }
  return new Error(message);
}
```

| Status / message | Cause | What to do |
|---|---|---|
| `… is not a field on Item on this site` | Bad `custom_is_gift_card_item` on a site without the field | Fix the client payload |
| `TypeError: DatabaseQuery.execute() got an unexpected keyword argument '…'` (500) | You sent a parameter the endpoint does not consume; it was splatted into the query builder | Only send documented parameters |
| Unexpectedly the full item list | `search` was empty, whitespace, or punctuation-only | §5 — track search mode client-side |
| Stale results under a newer query | Out-of-order responses | §4 — abort the previous request |
| CORS error in the console, no response | `allow_cors` missing your origin | §2 |

---

## 11. Limits

| | Value |
|---|---|
| `limit_page_length` | 1–500 (values outside are clamped, not rejected) |
| Rows ranked per query | 500 (`CANDIDATE_LIMIT`) |
| Typical latency | 1–4 ms server side |
| Server-side cache | 300s, cleared immediately on any item edit |
| Rate limit | none — debounce client-side |

The 300s cache is on the fuzzy term index only. A price or availability change is
never stale: those come from the live query on every request.

---

## 12. Testing checklist

- [ ] Type `biryani` one character at a time — no flicker, no stale results.
- [ ] Type fast, then delete fast — the final render matches the final term.
- [ ] `bir`, `briyani`, `ber`, `chikn` each surface the intended dish.
- [ ] `xylophone` renders your empty state, not a spinner forever.
- [ ] `!!!` does **not** render "no results" — it returns the full list (§5).
- [ ] Clearing the box returns to browse mode with the original ordering.
- [ ] Page 2 of a search shows different items and the same `total_count`.
- [ ] Changing the term resets `limit_start` to 0.
- [ ] Search inside a category filter stays inside it.
- [ ] With a bearer token and without one, results are identical.
- [ ] Slow network (throttle to 3G): aborts fire, no request pile-up.
