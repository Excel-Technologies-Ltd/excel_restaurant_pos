# Order guards: Turnstile, honeypot and idempotency

Three guards on `api.sales_invoices.add`, the public order endpoint. All are
optional from the client's point of view — an existing storefront that sends
neither keeps working exactly as before.

**Read this first, so neither gets mistaken for an access control.** Anonymous
checkout means every web order is attached to the same shared Customer
(`ArcPOS Settings.customer`), so an order carries no identity at all. What
actually separates a real order from a fake one is payment and a verified phone
number. These guards raise the cost of automated abuse and remove duplicate
orders; they do not make ordering authenticated.

**Order of execution matters and is not arbitrary:**

1. **Idempotency replay check** — first, because a Turnstile token is single
   use. A client retrying a dropped checkout re-sends the token it already
   spent, so verifying before this would refuse every genuine retry.
2. **Honeypot** — cheap and local.
3. **Turnstile** — last, because it is a network call, and only for orders that
   are genuinely new.

---

## Cloudflare Turnstile

The only one of the three that survives contact with a real attacker. Tokens are
single use and short lived, so copying the checkout request out of the network
tab and replaying it presents a token Cloudflare has already spent.

It still only proves a browser solved a challenge. Someone willing to place a
fake order by hand through the real checkout passes it every time.

### Setup

```json
// site_config.json -- the secret never goes in code or a fixture
{
  "arcpos_turnstile_secret": "0x4AAAAAAA...",
  "arcpos_turnstile_action": "checkout"
}
```

`arcpos_turnstile_action` is optional. Set it, and give the widget the matching
`data-action`, and a token minted for another widget on your site cannot be
replayed against the order endpoint.

**Presence of the secret is the on switch**, so the backend can ship before the
storefront starts sending tokens without refusing every order in between.
`arcpos_disable_turnstile: 1` is the kill switch.

The client sends the widget's token as `cf-turnstile-response`
(`cf_turnstile_response` and `turnstile_token` also accepted).

### What happens when things go wrong

This is the part worth reading twice — whose fault it is decides whether the
order goes through.

| Situation | Outcome |
|---|---|
| Valid token | Order placed |
| No token, Turnstile configured | **Refused**, no call to Cloudflare |
| Token rejected (`invalid-input-response`) | **Refused** |
| Token replayed or expired (`timeout-or-duplicate`) | **Refused** |
| `action` does not match the configured one | **Refused** |
| Cloudflare unreachable, timed out, 5xx, non-JSON | **Order placed**, logged |
| Our own keys wrong (`invalid-input-secret`) | **Order placed**, logged as misconfigured |
| Caller is signed in (POS terminal) | Skipped entirely |

Fail open on infrastructure, fail closed on a token Cloudflare actively
rejected. A restaurant must not stop taking orders during someone else's
outage, and a mistyped secret key should page an engineer, not close the
storefront. Both cases log loudly — check the Error Log for
*"Turnstile unavailable"* and *"Turnstile misconfigured"*.

The siteverify call is bounded at 5 seconds; checkout is on the critical path.

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

1. Add the Turnstile widget to checkout in **managed/invisible** mode, with a
   `data-action` matching `arcpos_turnstile_action`. Send its token as
   `cf-turnstile-response`. Reset the widget after a failed submit — a token
   cannot be used twice.
2. Render the three honeypot fields hidden (CSS, off-screen — **not**
   `type="hidden"`, which bots skip), and submit them empty.
3. Stamp `checkout_started_at` when the checkout screen opens; send it with the
   order.
4. Generate an idempotency key per checkout attempt; send it as
   `Idempotency-Key`; **reuse it on every retry**, including automatic ones.
   This is what lets a retry succeed despite carrying a spent Turnstile token.
5. On a 417 with *"could not be placed"*, show a generic failure and let the
   customer retry — do not auto-retry, and do not surface the reason.

## Verified

End-to-end over HTTP against the dev site, guest, no token:

Turnstile, using Cloudflare's published always-pass / always-fail test keys, so
the real siteverify call was exercised rather than a mock:

```
turnstile not configured   -> WEB-26-01367   (backend ahead of storefront)
configured, no token       -> 417 This order could not be placed
configured, with token     -> WEB-26-01368
retry w/ same spent token  -> WEB-26-01369   SAME order, not refused
always-fail secret         -> 417 This order could not be placed
```

Honeypot and idempotency:

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

46 unit tests, plus the unique index confirmed at the database level
(`non_unique=0`, a second row refused with `IntegrityError`).
