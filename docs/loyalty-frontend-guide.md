# Loyalty — frontend integration guide (pos-web, order-web)

The backend is the single source of truth. Frontends only display what the
APIs return and never compute balances themselves. Contract: `docs/loyalty-api.md`.

## order-web (storefront / app)

### Loyalty home
- `GET api.loyalty.me`.
  - `enrolled: false` and `can_enrol: true` → show a "Join" card → `POST api.loyalty.enrol`.
  - Enrolled → balance (`available_points`, `available_value` in `programme.currency`),
    pending (with "available after the return window"), the `expiring` banner,
    tier with a progress bar from `tier_progress`, and lifetime stats.
- Render `member_token` as a QR code ("Show at the counter"). Refresh it on every
  app open: a reissued pass invalidates the old one.
- Add-to-wallet buttons, only when `wallet.google_enabled` / `wallet.apple_enabled`:
  - Google: `GET api.loyalty.wallet.google_save_url` → open `data.url`.
  - Apple: `GET api.loyalty.wallet.apple_pass_link` → navigate to `data.url`
    (`window.location`). A navigation cannot carry the Bearer token, so the link
    is signed and lives five minutes; fetch a fresh one on each tap. iOS Safari
    hands the `.pkpass` to Wallet.
  - Show "Added" when `wallet.google` / `wallet.apple` is `Installed`.

### History
`GET api.loyalty.transactions?page=1&page_size=20` with type and date filters.
Positive points are green and negative red. Show `source_label`,
`campaign_title`, and `expiry_date` for credits. `status: Pending` means "not
yet spendable".

### Campaigns
`GET api.loyalty.campaigns`. Cards from `title`, `description` and `image`, with
a "Live now" badge when `live_now`. For weekly campaigns, show `recurrence_days`.

### Rewards
`GET api.loyalty.rewards`. Disable the button unless `affordable && eligible`,
and show `reason` when not eligible.
`POST api.loyalty.redeem_reward` with an `Idempotency-Key` header: generate a
UUID per tap and reuse it on retries. Show `coupon_code` and `valid_upto`. The
voucher is then applied through the existing coupon flow.

### Checkout
1. While the cart is a draft, `POST api.loyalty.preview_earning` with
   `sales_invoice` shows "You'll earn N points".
2. `GET api.loyalty.redemption_options?sales_invoice=…`. Hide the section when
   `redeemable` is false. Otherwise show a slider or stepper from `min_points` to
   `max_points` in steps of `step`.
   - Applied monetary value is `min(points * point_value, max_value)`.
   - When `data.disclaimer` or `data.breakage_amount > 0` is returned (e.g. 7 points
     covering a $12.20 bill), display the disclaimer notice:
     `"Points cover the full bill. Any remaining point value cannot be refunded or returned as change."`
3. `POST api.loyalty.apply_points` (or `remove_points`). Show `amount_due` as
   "To pay".
4. Pay as today: `api.payments.get_ticket` charges `amount_due`. If it returns
   `payment_required: false`, the points covered everything; go to the
   confirmation page. Getting the ticket holds the order's points until it is
   paid, so they can't be spent elsewhere meanwhile. If the points were spent
   before that, `get_ticket` fails with "Only N loyalty points are available
   now…": call `redemption_options` again, let the member pick new points, and
   retry. A card that has been charged always completes the order.
5. If the order changes after points are applied, call `redemption_options`
   again. The server clamps points silently when the order shrank.

### Preferences
`GET/POST api.loyalty.preferences` for the email and push toggles.

## pos-web (staff)

### Find the member
- Scan the QR (member token), or type a member number, phone or email →
  `GET api.loyalty.lookup?query=…`. Show name, masked contact, tier,
  `available_points` and `status`.
- Not a member → "Enrol" → `POST api.loyalty.staff_enrol` with the order.

### Use points on the order
- `GET api.loyalty.redemption_options?sales_invoice=…`, then
  `POST api.loyalty.apply_points`.
- **Value calculation & disclaimer:** The monetary tender value is
  `min(points * point_value, max_value)`. If `data.disclaimer` or `data.breakage_amount > 0`
  is returned, show the disclaimer under the slider/stepper so cashier and customer know
  that points cover the bill in full without cash change on the fractional remainder.
- When `points > step_up_threshold`, first `POST api.loyalty.request_otp {sales_invoice, points}`
  with the points about to be used: the code covers that amount only (a new
  amount needs a new code). The member reads out the code →
  `POST api.loyalty.verify_otp {sales_invoice, code, points}`,
  then apply or submit. Without it, submitting fails with "Verification Required".
- **Payments rows:** cash and card rows must total `rounded_total − value`
  (`grand_total` when rounding is off). Never add a loyalty row yourself; the
  server books it. The server refuses the submit, rather than leaving the
  order part-paid, when:
  - cash and card rows plus the points exceed the total ("Payments … plus
    loyalty points … exceed the order total");
  - a Loyalty Points row is sent with no points applied;
  - the points no longer fit the order's limits ("Loyalty points on this order
    were reduced to N. Update the payment and submit again."). Re-read
    `redemption_options`, re-price the rows and submit again.
- **Payment dialog** (`api.payment_entry.create_payment`): refuses a Loyalty
  Points row. Use `apply_points` instead.
- Dine-in orders already submitted to the kitchen can take points too. The
  points are spent immediately and the order's outstanding drops.
- Receipt: print `custom_loyalty_points_redeemed`, `custom_loyalty_redeem_value`
  and `custom_loyalty_points_earned`. Earned points appear once the order is paid.

### Corrections
`POST api.loyalty.adjust` with a reason and remarks. A cashier's adjustment
waits for a Loyalty Manager (Desk → Loyalty → Adjustments → Approve & Post).

### Lost phone / shared screenshot
`POST api.loyalty.reissue_pass` → the old QR stops working at lookup, and the
wallet passes update themselves.

## Redemption rules the frontend must follow (order-web and pos-web)

1. **Never compute the limit on the client.** `max_points` from
   `redemption_options` is the only upper bound. It is the smallest number of
   points that covers the whole bill (rounded up to `step`) when the programme's
   *Max % of Order* is 100, capped by `available_points`, *Max Points per Order*
   and the points the member has.
   Example (`point_value` 2.00, bill 17.40): `max_points = 9` (9 × 2.00 = 18.00).
   Sending 10 fails with `At most 9 points can be used on this order (40 available).`
2. **Bound the control with the response.** The slider, stepper and "Max" button
   run from `min_points` to `max_points` in steps of `step`. A typed number is
   clamped to that range before it is sent.
3. **Tender value** is `min(points × point_value, max_value)`. When
   `points × point_value > max_value` the response carries `breakage_amount` and
   `disclaimer`: show the disclaimer next to the control and on the receipt, and
   show `amount_due` (not the nominal value) as "To pay". The extra value is not
   refunded and not given as change.
4. **Save the order with its taxes and tip before reading the options.** The
   limit is measured against the invoice as stored on the server
   (`rounded_total`, else `grand_total`). A draft that has not been synced with
   the totals the till shows gives a lower `max_points` than the screen implies.
   If the till total and the server total differ, re-save the order first.
5. **Re-read `redemption_options` whenever the order changes** (item, tip, tax,
   customer, service type) and after any "At most N points" or "reduced to N"
   error, then let the user pick again.
6. **Amount due.** After `apply_points`, collect `amount_due` with the other
   tenders. When it is 0, do not ask for cash or card.

## Error handling
- A 401 from customer endpoints means refresh the token and retry. A 403 means
  "not your order".
- `ValidationError` messages are written for the user. Show them as-is (e.g.
  "At most 1,500 points can be used on this order (2,000 available).").
- Retrying `redeem_reward` with the same key is safe, and so is retrying
  `apply_points` with the same points.
