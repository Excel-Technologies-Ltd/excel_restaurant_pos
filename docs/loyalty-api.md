# Loyalty API

Contract for the ArcPOS loyalty programme (`shared/loyalty/`, `api/loyalty/`).
Design: `docs/loyalty-programme-implementation-plan.md`.

All endpoints are `/api/method/<route>`. Responses use the existing shape:

```json
{ "message": { "success": true, "message": "Loyalty account", "data": { } } }
```

Errors are standard Frappe errors (`exc_type`, `_server_messages`); 401 means
"sign in again" (the storefront retries after a token refresh), 403 means "not
yours / not allowed".

Customer endpoints always resolve the member from the session. They never
accept a customer id. With `ArcPOS Loyalty Settings.enabled = 0` they answer
"not available" and nothing earns or redeems anywhere.

## Customer (storefront / app)

| Route | Method | Params | Data |
| --- | --- | --- | --- |
| `api.loyalty.me` | GET | — | `{enrolled: false, can_enrol}` or the account summary below |
| `api.loyalty.enrol` | POST | — | account summary |
| `api.loyalty.transactions` | GET | `type` (comma list of Earn, Bonus, Redeem, Expire, Reverse, Adjust), `from_date`, `to_date`, `page`, `page_size` (≤ 100) | rows + `page`, `page_size`, `total` |
| `api.loyalty.campaigns` | GET | — | campaigns the member is eligible for (`title`, `description`, `image`, `starts`, `ends`, `recurrence`, `recurrence_days`, `live_now`, `upcoming`) |
| `api.loyalty.rewards` | GET | — | catalogue rows with `affordable`, `eligible`, `reason`, `remaining_stock` |
| `api.loyalty.redeem_reward` | POST | `reward`; **`Idempotency-Key` header** (or `idempotency_key` body) | `{transaction, reward, points, coupon_code, valid_upto, status}` — replaying the key returns the same voucher |
| `api.loyalty.preview_earning` | POST | `sales_invoice`, **or** `items` (JSON `[{item_code, qty, rate}]`) + `order_from` + `service_type` | `{eligible, points, value, pending_days, awards[]}` |
| `api.loyalty.redemption_options` | GET | `sales_invoice` | `{redeemable, available_points, min_points, max_points, step, point_value, max_value, applied_points, applied_value, step_up_threshold}` |
| `api.loyalty.apply_points` | POST | `sales_invoice`, `points` | `{sales_invoice, points, value, grand_total, amount_due, account}` |
| `api.loyalty.remove_points` | POST | `sales_invoice` | same shape |
| `api.loyalty.preferences` | GET / POST | `notify_email`, `notify_push` (0/1) | `{notify_email, notify_push}` |
| `api.loyalty.wallet.google_save_url` | GET | — | `{url}` — open it, or use it as the "Add to Google Wallet" link |
| `api.loyalty.wallet.apple_pass` | GET | — | `.pkpass` download (`application/vnd.apple.pkpass`) — native apps that can send the `Authorization` header |
| `api.loyalty.wallet.apple_pass_link` | GET | — | `{url, expires_in: 300}` — a signed five-minute link for browsers; navigate to `url` (iOS Safari offers Add to Wallet) |
| `api.loyalty.wallet.apple_pass_download` | GET (guest) | `t` (from `apple_pass_link`) | `.pkpass` download; expired or tampered link → 403 |

### Account summary

```json
{
  "enrolled": true,
  "member_number": "LM-8F3K2Q9X",
  "status": "Active",
  "customer_name": "Jane Doe",
  "tier": "Silver",
  "tier_progress": { "next_tier": "Gold", "threshold": 1000, "remaining": 240, "basis": "Lifetime Spend" },
  "available_points": 1250, "available_value": 12.5,
  "pending_points": 80, "pending_value": 0.8,
  "expiring": { "date": "2026-11-30", "points": 300 },
  "lifetime": { "earned": 4000, "redeemed": 2600, "expired": 150 },
  "preferences": { "notify_email": 1, "notify_push": 1 },
  "wallet": { "google": "Installed", "apple": null, "google_enabled": true, "apple_enabled": true },
  "programme": { "name": "Rewards", "point_value": 0.01, "currency": "CAD", "terms": "<p>…</p>" },
  "member_token": "AL1.LM-8F3K2Q9X.1.3f9a0c…"
}
```

`member_token` is what the in-app QR code and the wallet passes carry. It
identifies the member and never authorises a spend on its own.

### Transaction row

`name, posting_datetime, transaction_type, points (signed), status, available_on,
expiry_date, remaining_points, source_name, source_label ("Order SINV-…",
"Voucher RWD…"), campaign, campaign_title, event_type, remarks, currency_value`.

## Staff (POS)

Need a staff role (System Manager, ArcPOS Loyalty Manager, ArcPOS Manager,
ArcPOS Register User, Restaurant Manager, Restaurant Cashier, Restaurant Waiter).

| Route | Method | Params | Data |
| --- | --- | --- | --- |
| `api.loyalty.lookup` | GET | `query`: scanned token, member number, phone or email | up to 10 summaries, with `customer`, masked `email` / `phone`, no token |
| `api.loyalty.staff_enrol` | POST | `sales_invoice` or `customer` | summary (also stamps the invoice) |
| `api.loyalty.apply_points` / `remove_points` | POST | as above | as above — staff may act on any order |
| `api.loyalty.request_otp` | POST | `sales_invoice`, `points` | `{sent_to: "j***@e***.com", expires_in: 300, points}` — the code authorises exactly `points`, and the member's message states it |
| `api.loyalty.verify_otp` | POST | `sales_invoice`, `code`, `points` (optional) | `{verified: true}`; wrong code → ValidationError; `points` different from the requested amount → ValidationError |
| `api.loyalty.adjust` | POST | `account`, `points` (signed), `reason`, `remarks`, `expiry_date` | `{adjustment, approval_status, docstatus}` — posted immediately for a Loyalty Manager under the approval threshold, otherwise left Pending Approval |
| `api.loyalty.reissue_pass` | POST | `account` | summary; the old barcode stops working. Managers only (Loyalty Manager, Restaurant Manager, ArcPOS Manager) |

## Integrations

| Route | Auth | Params |
| --- | --- | --- |
| `api.loyalty.events.emit` | API key of a user with ArcPOS Loyalty Manager | `event_code`, `customer`, `reference` (required; the idempotency key), `payload` (JSON; `payload.amount` feeds spend rules) → `{entries, points}` |
| `api.loyalty.wallet.google_callback` | Google-signed (ECv2SigningOnly) + `?token=` callback secret | Google posts here; nothing to call |
| `/loyalty-wallet/apple/v1/...` | `Authorization: ApplePass <token>` | Apple PassKit web service; nothing to call |

## Points tender rules

- Points are a payment method (Mode of Payment *Loyalty Points*), not a
  discount. Tax is on the full order.
- Limits: `min_redeem_points`, multiples of `redeem_increment`,
  `max_redeem_points_per_order`, `max_redeem_percent_of_order` and the amount
  still due.
- Draft orders: `apply_points` only reserves; the points are spent when the
  order is submitted (and refused then if another order spent them first).
  Submitted unpaid orders (dine-in sent to the kitchen): `apply_points` spends
  at once and records the points payment.
- Whoever collects the rest must charge `amount_due`, not `grand_total`. The
  Moneris checkout already does (`api.payments.get_ticket` /
  `receipt_payment`). When points cover the whole order, `get_ticket` returns
  `{payment_required: false}` and submits the order itself.
- Changing applied points discards any Moneris ticket already issued for the order.
- POS payments rows (`custom_with_arcpos_payment`) must add up to at most
  `grand_total - custom_loyalty_redeem_value`. A loyalty row in `payments` is
  ignored by `create_payment_entry`; the loyalty module books it.

## Invoice fields

| Field | Meaning |
| --- | --- |
| `custom_loyalty_account` | Member account (read only) |
| `custom_loyalty_points_redeemed` | Points applied as tender |
| `custom_loyalty_redeem_value` | Their value (read only) |
| `custom_loyalty_points_earned` | Points awarded for this order, for receipts |
| `custom_loyalty_verified` | Step-up code verified (display only — the proof is server-side) |

## Setup checklist

1. Migrate. The patches create Mode of Payment **Loyalty Points**, hide
   ERPNext's native loyalty fields, and install the built-in event types
   (`customer_signup`, `first_order`, `birthday`, `feedback_submitted`, `referral`).
2. Create accounts: *Loyalty Points Liability* (current liability) and
   *Loyalty Programme Expense*.
3. Create an **ArcPOS Loyalty Programme** (company, point value, base rule
   e.g. Spend Rate 1 point per 1.00, pending days, expiry, redemption limits,
   tiers) and set it Active.
4. **ArcPOS Loyalty Settings**: active programme, liability / expense accounts
   (saving maps the loyalty Mode of Payment to the liability account),
   excluded walk-in customers, voucher pricing rule, email templates. Then tick
   **Enabled**.
5. Wallets (optional): Google issuer id + service account key + save origins;
   Apple pass type id, team id, `.p12` + password, WWDR G4 certificate,
   `Web Service URL = https://<site>/loyalty-wallet/apple`, pass icon (PNG).
6. Python dependencies: `google-auth`, `httpx[http2]` (in `pyproject.toml`).

## Decisions taken where the plan left options open

| Plan item | Implemented |
| --- | --- |
| D1 redemption model | Tender; tax on the full order |
| D2 liability | Daily true-up Journal Entry (Settings: Daily / Monthly / Off) |
| D3 earning | When fully paid; `pending_days` configurable (0 = immediately) |
| D4 with coupon / gift card | Allowed; points cap against the total left after those discounts |
| D5 backfill | None; one-off bonuses via Adjustment |
| D6 third-party channels | No earn, no redeem (they match no loyalty channel) |
| D9 step-up OTP | Off by default (`step_up_threshold_points = 0`) |
| D10 Apple routing | `page_renderer`; a scoped `before_request` hook moves the `ApplePass` header out of Frappe's auth path and carries DELETE as POST |
| Customer `after_insert` enrolment | Sign-up enrolment is called from `ensure_customer_for_user`, which every storefront sign-up path uses (a Customer insert happens before the User Permission exists) |
| `feedback_submitted` | Fired when ArcPOS Feedback is *completed* (`is_completed = Yes`), not on insert — the row is created automatically at submit |
| Adjustment workflow | Built into the doctype (Draft / Pending Approval / Approved / Rejected + Approve / Reject actions) rather than a Frappe Workflow record |
| Free-item rewards | A flat voucher worth the item's selling price, valid only on orders that contain the item |
| Report naming | Prefixed "Loyalty …" to avoid clashing with ERPNext CRM reports |
