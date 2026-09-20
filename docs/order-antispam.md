# Order guards: honeypot and idempotency

Two guards on `api.sales_invoices.add`, the public order endpoint. Both are
optional from the client's point of view — an existing storefront that sends
neither keeps working exactly as before.

**Read this first, so neither gets mistaken for an access control.** Anonymous
checkout means every web order is attached to the same shared Customer
(`ArcPOS Settings.customer`), so an order carries no identity at all. What
actually separates a real order from a fake one is payment and a verified phone
number. These two guards raise the cost of automated abuse and remove duplicate
orders; they do not make ordering authenticated.

---

## Idempotency

**The problem it solves:** a checkout that times out on a phone, a double
tapped *Place Order*, a retry from a flaky connection. Each currently makes a
second invoice and a second meal.

**Client contract.** Generate one key per checkout *attempt* and reuse it on
every retry of that attempt. A new attempt gets a new key.

```
POST /api/method/api.sales_invoices.add
Idempotency-Key: 8f14e45f-ceea-467a-93cb-9a1d5b1c1f37
```

The body keys `idempotency_key` / `idempotencyKey` work too, for clients that
cannot set headers. The header wins if both are present.

| | Behaviour |
|---|---|
| First request with a key | Creates the order, stamps the key on it |
| Any later request, same key | Returns **the same order**, creates nothing |
| Different key | A genuinely new order |
| No key | Unchanged — exactly as before |
| Malformed key | 417, `Idempotency-Key must be 8 to 128 characters…` |

Format: 8–128 characters of `A-Z a-z 0-9 . _ : -`. A UUID or ULID is ideal.

**The guarantee is the database, not a lookup.** The key is stored in
`Sales Invoice.custom_idempotency_key` with a **unique index**. Two simultaneous
retries both see no existing order, both try to insert, and MariaDB refuses the
second — which is precisely the case a check-then-insert gets wrong, and
precisely what a flaky connection produces. The loser then returns the winner's
order.

The insert is wrapped in a savepoint: a duplicate-key error leaves the
transaction unusable for the lookup that follows unless it is rolled back first.

A site that has not migrated yet (no column) keeps taking orders — the guard
disables itself rather than refusing every order.

## Honeypot

Two cheap bot checks, both on the create path only. The update path names an
existing invoice, so it cannot conjure a second order however often it is
retried.

**Hidden fields.** The checkout renders `website`, `fax_number` and
`company_website` out of sight. A human never fills one, so any value means the
request was machine generated. They are named after plausible form fields on
purpose — a field called `honeypot` just teaches a bot to skip it.

**Submission timing.** If the client sends `checkout_started_at` (a timestamp
stamped when the checkout screen opens), an order arriving less than
**3 seconds** later is refused. Omit the field and no timing check runs.
Timestamps more than 6 hours old, or in the future, are ignored — a stale tab or
a skewed clock should not cost someone their dinner.

Rejections return a bland *"This order could not be placed. Please try again."*
and log the real reason server-side. Naming the field that fired would be a free
tutorial on evading it.

**Kill switch.** `arcpos_disable_order_honeypot: 1` in `site_config.json`
disables both checks, so a broken client release cannot take ordering down at
7pm on a Friday.

### What the honeypot does not do

It catches bots that fill every field they find. It does **not** catch someone
who opened the network tab, copied the request the real checkout makes and
replayed it — their copy simply does not carry the honeypot field, and can
carry any `checkout_started_at` they like.

Making the timing check a real gate means signing it: have the checkout screen
fetch a short-lived server-signed token, and require it on the order. That also
gives replay protection. It needs a frontend change, so it is deliberately not
built here.

## Frontend changes needed

1. Render the three honeypot fields hidden (CSS, off-screen — **not**
   `type="hidden"`, which bots skip), and submit them empty.
2. Stamp `checkout_started_at` when the checkout screen opens; send it with the
   order.
3. Generate an idempotency key per checkout attempt; send it as
   `Idempotency-Key`; **reuse it on every retry**, including automatic ones.
4. On a 417 with *"could not be placed"*, show a generic failure and let the
   customer retry — do not auto-retry, and do not surface the reason.

## Verified

End-to-end over HTTP against the dev site, guest, no token:

```
1. honeypot filled    -> 417 This order could not be placed
2. instant submit     -> 417 This order could not be placed
3. human-paced        -> WEB-26-01364
4. junk key           -> 417 Idempotency-Key must be 8 to 128 characters
5. first with key     -> WEB-26-01365
   retry 1/2/3        -> WEB-26-01365  (same order, three times)
6. different key      -> WEB-26-01366
7. no key at all      -> WEB-26-01367
rows carrying the key -> 1
```

28 unit tests, plus the unique index confirmed at the database level
(`non_unique=0`, a second row refused with `IntegrityError`).
