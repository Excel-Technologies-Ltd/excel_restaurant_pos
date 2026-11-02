# Customer Loyalty Programme — Implementation Plan

> **Status:** Draft — for review before development
> **App:** `excel_restaurant_pos` (ArcPOS / ERPNext v14.92) — **production system**
> **Date:** 2026-10-18
> **Note:** Scope is full production delivery. The phases in §15 are sequencing, not MVP cut lines.

---

## 1. Purpose

This document plans an ArcPOS-native Customer Loyalty Programme that covers:

- configurable earning rules (spend, items, seasonal campaigns, events, custom rules)
- redemption policies
- point expiry
- membership tiers
- a customer-facing loyalty account
- an admin console with reports
- Google Wallet and Apple Wallet passes

The backend is the **single source of truth** for balances. Wallet passes only display data the backend pushes to them.

It is a **review artifact**: no loyalty logic exists in the app yet.

---

## 2. Build vs. ERPNext Loyalty Program

ERPNext v14 ships `Loyalty Program`, `Loyalty Program Collection` and `Loyalty Point Entry`. Here is how they compare with the requirements:

| Requirement | ERPNext v14 | Decision |
| --- | --- | --- |
| Spend-based earning, conversion factor, expiry days | ✅ | Re-implemented (see below) |
| Item / item group / brand / quantity earning | ❌ | Custom rules engine |
| Seasonal campaigns, multipliers, bonuses, stacking | ❌ (one programme per customer) | Custom campaigns |
| Event-based points (sign-up, etc.) | ❌ (invoice-only) | Custom event emitter |
| Min/max redemption, % of order caps | ❌ | Custom policy |
| Pending points, expiry entries in ledger | ❌ (expiry is a date filter) | Custom lot ledger |
| Manual adjustments with approval + audit | ❌ | Custom adjustment doc |
| Expiry / earn / redeem notifications | ❌ | Custom |
| Tiers beyond lifetime spend, tier benefits | ⚠️ minimal | Custom tiers |
| Liability / campaign reports | ⚠️ minimal | Custom reports |
| Google / Apple Wallet | ❌ | Custom wallet layer |

**Decision:** we build a separate module, `shared/loyalty/`, with its own DocTypes prefixed `ArcPOS Loyalty …`. This avoids name clashes with ERPNext's doctypes.

- ERPNext's native loyalty is **switched off for ArcPOS invoices**: `dont_create_loyalty_points = 1` is set in `validate`, and its fields are hidden through property setters. Otherwise a Sales Invoice would issue points twice.
- Existing custom fields on `Loyalty Program` in `fixtures/custom_field.json` are only accounting dimensions (`excel_*`), so no migration is needed.

---

## 3. Scope

### In scope

| Area | Description |
| --- | --- |
| **Ledger** | Immutable, lot-based points ledger with idempotency keys; earn / bonus / redeem / expire / reverse / adjust |
| **Earning** | Base spend rule, item/category/brand/qty rules, thresholds, multipliers, campaign bonuses, event rules |
| **Campaigns** | Time-bound, prioritised, stackable/exclusive, budgeted; Draft → Active → Paused → Ended |
| **Redemption** | Points as tender on an order (partial and combined with other payment methods); reward catalogue that issues coupons |
| **Policies** | Conversion rate, min/max redemption, % of order cap, pending period, expiry, negative-balance policy |
| **Reversal** | Invoice cancel and credit notes reverse earned points and restore redeemed points |
| **Tiers & segments** | Qualification rules, earn multipliers, benefits, segment-based eligibility |
| **Customer account** | APIs for balance, value, pending, expiring, history, campaigns, rewards, redemption, notification preferences |
| **Notifications** | Earned, redeemed, expiring-soon, tier change (email + push) |
| **Admin** | Desk workspace, campaign management, adjustments with approval, number cards, reports |
| **Accounting** | Loyalty liability account, redemption tender, daily liability true-up |
| **Google Wallet** | Loyalty class/object, Save link, live updates, messages, state changes |
| **Apple Wallet** | Signed `.pkpass`, PassKit web service, APNs push updates, voiding/reissue |
| **Staff POS** | Member lookup (QR scan, phone, email), apply/remove points, step-up verification |

### Out of scope (unless requested)

- Referral programme (the event emitter supports it later with no schema change)
- Coalition / partner points, points transfer between customers
- Multi-currency point valuation
- Frontend implementation in `pos-web` / `order-web`. Those are separate repos; this delivery ships the API contract plus a frontend guide (as was done for gift cards).

---

## 4. Core Principles

1. **The ledger is the truth.** Balances on `ArcPOS Loyalty Account` are a cache, recomputed from the ledger inside the same DB transaction that writes it, under a row lock.
2. **Immutable entries.** Ledger rows are never edited or deleted. Corrections are new entries (`Reverse`, `Adjust`). The only system-mutated fields are `remaining_points` (lot consumption) and `status` (Pending → Available → Expired/Consumed), and those changes are tracked.
3. **Idempotent writes.** Every ledger write carries a deterministic `idempotency_key` with a **unique DB index**, the same approach as `shared/sales_invoice/idempotency.py`. Retries, double hooks and replayed jobs cannot double-issue or double-redeem.
4. **Lock before spending.** Redeem, expire and reverse take `SELECT … FOR UPDATE` on the account row, re-read the available balance from the ledger, then write.
5. **Wallets are views.** Wallet passes never hold state the backend lacks. Sync is debounced, retried and reconciled nightly.
6. **Configurable, not coded.** Earning logic is data: rules, campaigns, tiers and segments. New *event types* need only an emitter call or the external events API.
7. **Feature flag.** With `ArcPOS Loyalty Settings.enabled = 0`, every hook is a no-op.

---

## 5. Data Model

All DocTypes live in module **Excel Restaurant Pos** under `excel_restaurant_pos/excel_restaurant_pos/doctype/`.

### 5.1 ArcPOS Loyalty Settings (Single)

Infrastructure only. Business policy lives on the Programme (§5.2).

| Field | Type | Purpose |
| --- | --- | --- |
| `enabled` | Check | Master feature flag |
| `active_programme` | Link → ArcPOS Loyalty Programme | The programme new activity posts to |
| `auto_enrol_on_signup` / `auto_enrol_on_first_order` | Check | Enrolment triggers |
| `excluded_customers` | Table MultiSelect → Customer | Walk-in / default POS customers that never enrol |
| `loyalty_mode_of_payment` | Link → Mode of Payment | Tender used for redemption (e.g. "Loyalty Points") |
| `liability_account` | Link → Account | Outstanding points liability |
| `expense_account` | Link → Account | Contra account for the liability true-up (marketing expense) |
| `cost_center` | Link → Cost Center | |
| `liability_true_up_frequency` | Select (Daily/Monthly/Off) | Journal Entry cadence (§9) |
| `adjustment_approval_threshold` | Int | Adjustments with \|points\| above this need approval |
| `notify_email` / `notify_push` | Check | Defaults for new accounts |
| `member_token_secret` | Password | HMAC secret for member barcodes (§8.1) |
| `step_up_threshold_points` | Int | Redemptions above this need OTP at POS (0 = off) |
| **Google Wallet section** | | `google_enabled`, `google_issuer_id`, `google_service_account_json` (Attach, private), `google_class_suffix`, `google_callback_secret` |
| **Apple Wallet section** | | `apple_enabled`, `apple_pass_type_id`, `apple_team_id`, `apple_pass_certificate` (Attach .p12, private), `apple_pass_certificate_password` (Password), `apple_wwdr_certificate` (Attach), `apple_web_service_url`, `apple_apns_environment` (Production/Sandbox) |
| **Branding section** | | `pass_logo`, `pass_icon`, `pass_strip_image`, `pass_background_color`, `pass_foreground_color`, `pass_label_color`, `programme_display_name` |

### 5.2 ArcPOS Loyalty Programme

One **Active** programme per company at a time.

| Field | Type | Purpose |
| --- | --- | --- |
| `programme_name` | Data | |
| `company` | Link → Company | |
| `status` | Select: Draft / Active / Paused / Ended | Paused = no earning or redemption; balances kept |
| `start_date` / `end_date` | Date | End date optional |
| `point_value` | Currency | Currency value of **1 point** at redemption (e.g. 0.01) |
| `points_rounding` | Select: Floor / Round / Ceil | Earning rounding (points are integers) |
| `earn_basis` | Select: Net Total (excl. tax) / Grand Total | Base amount |
| `exclude_item_groups` | Table MultiSelect → Item Group | E.g. gift cards, delivery, tips |
| `exclude_gift_card_items` | Check (default 1) | Selling gift cards earns no points |
| `earn_on_loyalty_paid_amount` | Check (default 0) | Whether the portion paid with points earns |
| `earning_channels` | Check ×4 | Dine-in / In Store Pickup / Online Delivery / Online Pickup (channel model from the gift card plan §5) |
| `pending_days` | Int | Earned points stay Pending for N days (return window); 0 = immediate |
| `earn_on` | Select: Paid / Submitted | Earn when the invoice is fully paid (default) or on submit |
| `expiry_mode` | Select: Fixed Days per Lot / Rolling Inactivity / Never | |
| `expiry_days` | Int | Lot lifetime, or inactivity window |
| `expiry_notice_days` | Data (e.g. `30,7,1`) | When to send expiring-soon notices |
| `min_redeem_points` | Int | Minimum points per redemption |
| `max_redeem_points_per_order` | Int | 0 = unlimited |
| `max_redeem_percent_of_order` | Percent | Cap as % of order total |
| `redeem_increment` | Int | Redeem in multiples of N (e.g. 100) |
| `redemption_channels` | Check ×4 | Where points can be spent |
| `allow_negative_balance_on_reversal` | Check | If points already spent when an order is refunded: go negative (offset future earning) or reverse only what remains |
| `base_rules` | Table → ArcPOS Loyalty Rule | Always-on rules (e.g. 1 pt per 1 currency unit) |
| `base_rule_items` | Table → ArcPOS Loyalty Rule Item | Item filters for base rules |
| `tiers` | Table → ArcPOS Loyalty Tier | §5.6 |
| `tier_basis` | Select: Lifetime Spend / Rolling 12-Month Spend / Rolling 12-Month Points | |
| `tier_review` | Select: Upgrade Immediately, Downgrade at Review / Continuous | |
| `terms` | Text Editor | Shown in app and on pass back |

### 5.3 ArcPOS Loyalty Account

One per Customer. Autoname: random member number, e.g. `LM-8F3K2Q9X` (used on the pass, never the Customer ID).

| Field | Type | Purpose |
| --- | --- | --- |
| `customer` | Link → Customer (unique) | |
| `user` | Link → User | Storefront account if any (via `shared/customer_access.customer_of`) |
| `programme` | Link | |
| `member_number` | Data (unique) | Human-readable / barcode identity |
| `token_version` | Int | Bumped on reissue to invalidate old barcodes |
| `status` | Select: Active / Suspended / Closed | Suspended = no earn/redeem; Closed = voids passes |
| `tier` | Data (tier name from programme) | Current tier |
| `tier_since` / `tier_review_date` | Date | |
| `enrolled_on` | Datetime | |
| `enrolment_source` | Select: Signup / First Order / POS / Admin / Import | |
| *Cached (read-only)* | Int | `available_points`, `pending_points`, `lifetime_earned`, `lifetime_redeemed`, `lifetime_expired`, `qualifying_value` |
| `next_expiry_date` / `next_expiry_points` | Date / Int | For app + pass |
| `last_activity_at` | Datetime | Rolling-inactivity expiry |
| `notify_email` / `notify_push` | Check | Preferences |

### 5.4 ArcPOS Loyalty Transaction (the ledger)

Not submittable. Created only by service code (`ignore_permissions`). No role has write/delete; `on_trash` and `validate` (when not new) raise. `track_changes = 1`.

| Field | Type | Purpose |
| --- | --- | --- |
| `account` / `customer` | Link | |
| `programme` | Link | |
| `posting_datetime` | Datetime | |
| `transaction_type` | Select: Earn / Bonus / Redeem / Expire / Reverse / Adjust | |
| `points` | Int (signed) | + credit, − debit |
| `status` | Select: Pending / Available / Consumed / Expired / Reversed | Credits only; debits are `Consumed` |
| `available_on` | Date | Pending → Available date |
| `expiry_date` | Date | Credits only |
| `remaining_points` | Int | Unconsumed part of a credit lot |
| `currency_value` | Currency | `points × point_value` at posting time (for reports) |
| `source_doctype` / `source_name` | Dynamic Link | Sales Invoice, ArcPOS Loyalty Adjustment, Customer, Coupon Code, … |
| `campaign` / `rule_id` | Link / Data | Which campaign/rule produced it |
| `event_type` | Link → ArcPOS Loyalty Event Type | For event awards |
| `reverses` | Link → ArcPOS Loyalty Transaction | For Reverse entries |
| `idempotency_key` | Data, **unique index** | See §7.6 |
| `remarks` | Small Text | |
| `allocations` | Table → ArcPOS Loyalty Allocation | For debits: lots consumed |

**ArcPOS Loyalty Allocation** (child): `lot` (Link → Transaction), `points` (Int), `lot_expiry_date` (Date). It lets a reversed redemption restore the exact lots, with their original expiry.

**Indexes:** `(account, status, expiry_date)`, `(source_doctype, source_name)`, `(campaign, posting_datetime)`, unique `idempotency_key`.

### 5.5 ArcPOS Loyalty Rule (child table)

Used by both `Programme.base_rules` and `Campaign.rules`.

| Field | Type | Purpose |
| --- | --- | --- |
| `rule_id` | Data | Stable id (auto, short hash); used in idempotency keys and item filters |
| `rule_name` | Data | |
| `enabled` | Check | |
| `trigger` | Select: Purchase / Event | |
| `event_type` | Link → ArcPOS Loyalty Event Type | When trigger = Event |
| `rule_type` | Select | **Spend Rate** (N pts per X spent) · **Spend Threshold** (spend ≥ X → N pts) · **Item Quantity** (N pts per matching qty) · **Item Spend** (N pts per X spent on matching items) · **Fixed Bonus** (N pts when conditions met) · **Multiplier** (× factor) |
| `points` | Int | |
| `per_amount` | Currency | For rate rules |
| `multiplier` | Float | For Multiplier |
| `multiplier_scope` | Select: Base Points / All Points Before Multipliers | |
| `applies_to` | Select: All Items / Filtered | Filtered = lines matching the rule's `Rule Item` rows |
| `min_order_amount` / `min_qty` | Currency / Float | |
| `order_number` | Int | E.g. 1 = first order only |
| `max_points_per_order` | Int | |
| `condition` | Code (Python expression) | Optional advanced condition, evaluated with `frappe.safe_eval` on a restricted context (§7.3) |
| `priority` | Int | |
| `exclusive` | Check | Stops lower-priority rules in the same scope |

**ArcPOS Loyalty Rule Item** (child; a separate grid on the parent, because Frappe has no child-of-child tables): `rule_id`, `applies_to` (Item / Item Group / Brand), `value` (Dynamic Link).

### 5.6 ArcPOS Loyalty Tier (child of Programme)

| Field | Type | Purpose |
| --- | --- | --- |
| `tier_name` | Data | Bronze / Silver / Gold |
| `rank` | Int | Ordering |
| `threshold` | Float | Per `tier_basis` |
| `earn_multiplier` | Float | Applied to base points |
| `benefits` | Small Text | Shown in app / pass back |
| `pass_color` | Color | Pass background override |

Tier is evaluated after each earn and nightly (§7.8). Every change writes an `ArcPOS Loyalty Tier Change` row (account, from, to, reason, at) for audit.

### 5.7 ArcPOS Loyalty Campaign

| Field | Type | Purpose |
| --- | --- | --- |
| `campaign_name` | Data | |
| `programme` | Link | |
| `status` | Select: Draft / Scheduled / Active / Paused / Ended | Scheduler moves Scheduled ↔ Active ↔ Ended by window |
| `start_datetime` / `end_datetime` | Datetime | |
| `recurrence` | Select: None / Weekly / Yearly | E.g. every Friday, annual festival |
| `recurrence_days` | Data | E.g. `Fri,Sat` |
| `priority` | Int | |
| `stackable` | Check | If unchecked, only the highest-priority non-stackable campaign applies |
| `eligible_channels` | Check ×4 | |
| `eligible_tiers` | Small Text (tier names) | Empty = all |
| `eligible_segments` | Table MultiSelect → ArcPOS Loyalty Segment | |
| `eligible_territories` | Table MultiSelect → Territory | Outlet scoping |
| `points_budget` | Int | Campaign stops awarding at budget |
| `per_customer_cap` | Int | |
| `rules` | Table → ArcPOS Loyalty Rule | |
| `rule_items` | Table → ArcPOS Loyalty Rule Item | |
| `display_in_app` | Check | Shown in "Active campaigns" |
| `title` / `description` / `image` | | Customer-facing copy |
| *Stats (read-only)* | | `points_issued`, `participants`, `orders` |

### 5.8 ArcPOS Loyalty Event Type

`event_code` (unique, e.g. `customer_signup`, `first_order`, `birthday`, `feedback_submitted`, `referral`), `description`, `once_per_customer` (Check), `cooldown_days` (Int). An admin can create a new type and fire it through the events API (§10.3) with no code change.

### 5.9 ArcPOS Loyalty Segment

`segment_name` and filters: customer group, territory, tier, min lifetime spend, enrolled between, order count between, last order within N days. Optionally a static member table. Membership is evaluated on demand and cached per account for 1 h in Redis.

### 5.10 ArcPOS Loyalty Reward (reward catalogue)

| Field | Type | Purpose |
| --- | --- | --- |
| `reward_name` / `description` / `image` | | |
| `reward_type` | Select: Order Discount Voucher / Free Item | |
| `points_cost` | Int | |
| `discount_type` / `discount_value` | | For voucher |
| `free_item` | Link → Item | |
| `voucher_validity_days` | Int | |
| `eligible_tiers` / `stock_limit` / `per_customer_limit` | | |
| `active_from` / `active_to` | | |

Redeeming a reward debits points and **issues a single-use Coupon Code**, reusing the existing coupon engine (`shared/coupon/`), linked to the customer email. A voucher that expires unused refunds the points with a Reverse entry.

### 5.11 ArcPOS Loyalty Adjustment (submittable, approval)

`account`, `points` (signed), `reason` (Select: Goodwill / Correction / Promotion / Migration / Other), `remarks` (mandatory), `expiry_date` (optional override), `requires_approval` (auto when |points| > settings threshold), plus a Workflow: Draft → Pending Approval → Approved (submit) / Rejected. On submit it posts an `Adjust` ledger entry with key `adjust:{name}`. Cancelling it posts a Reverse. The audit trail is docstatus + Version + ledger row.

### 5.12 Wallet DocTypes

**ArcPOS Wallet Pass**: `account`, `platform` (Google/Apple), `object_id` (Google object id / Apple serial), `auth_token_hash` (Apple), `status` (Issued / Installed / Removed / Voided), `last_synced_at`, `last_synced_hash` (hash of the rendered payload; skip the push when unchanged), `last_error`, `retry_count`.

**ArcPOS Wallet Device Registration** (Apple): `device_library_id`, `push_token`, `pass` (Link), `registered_at`. Unique on (`device_library_id`, `pass`).

### 5.13 Sales Invoice custom fields

| Field | Type | Purpose |
| --- | --- | --- |
| `custom_loyalty_account` | Link → ArcPOS Loyalty Account | Resolved from customer |
| `custom_loyalty_points_redeemed` | Int | Points applied on this order |
| `custom_loyalty_redeem_value` | Currency | Value of those points |
| `custom_loyalty_points_earned` | Int (read-only) | Total awarded, for receipt/print |
| `custom_loyalty_verified` | Check (hidden) | Step-up OTP satisfied for this order |

Property setters hide ERPNext's native `loyalty_points_redemption` section on Sales Invoice and the `loyalty_points_tab` on Customer, to avoid confusion.

---

## 6. Lifecycle States

**Ledger credit lot:** `Pending → Available → (Consumed | Expired | Reversed)`. A lot can be partly consumed (`remaining_points > 0`) while Available.

**Account:** `Active ⇄ Suspended → Closed`. Closing voids wallet passes and expires remaining points (Expire entry with remark).

**Campaign:** `Draft → Scheduled → Active ⇄ Paused → Ended`. Rule edits are blocked while Active. Changes need Pause → edit → Resume, and each version is kept via `track_changes`.

**Wallet pass:** `Issued → Installed → (Removed | Voided)`; reissue voids the old pass and issues a new one.

---

## 7. Core Workflows

### 7.1 Enrolment

- **Sign-up**: `overrides/user.py:sign_up` → `shared/web_customer.ensure_customer_for_user` → `loyalty.enrol(customer, source="Signup")`, then `loyalty.emit("customer_signup", customer)`. That covers the "5 points for every newly registered customer" example.
- **First order** (POS / walk-in with a named customer): enrol on first paid invoice if `auto_enrol_on_first_order`.
- **Admin / import**: Desk action + Data Import.
- Enrolment is idempotent: the unique `customer` on Account.
- Customers in `excluded_customers` (walk-in / default POS customer) are **never** enrolled.

### 7.2 Earning on a purchase

Trigger:

- `Sales Invoice.on_submit` when `earn_on = Submitted`, or when the invoice is already paid at submit.
- `Payment Entry.on_submit` (next to `doc_event/payment_entry/settle_order_status`) when the invoice becomes fully paid. ERPNext sets Paid via `db_set`, so the invoice itself fires no event.

Both paths call `loyalty.earning.award_for_invoice(invoice)`, which is idempotent per rule. Its steps:

1. Guard: enabled, programme Active, account Active, channel allowed, not `is_return`, customer not excluded.
2. Build an **order context**: customer, account, tier, segments, channel (`custom_order_from` + `custom_service_type`), territory, posting datetime, order number for this customer, and lines (`item_code`, `item_group`, `brand`, `qty`, `net_amount`) after removing excluded groups and gift card items. Also `eligible_amount` = per `earn_basis`, minus the loyalty-paid portion unless `earn_on_loyalty_paid_amount`.
3. `rules.evaluate(context)` → list of awards (§7.3).
4. For each award: insert an Earn (base) or Bonus (campaign) ledger row with `status = Pending` (or Available when `pending_days = 0`), `available_on`, `expiry_date = available_on + expiry_days`, and key `earn:{invoice}:{scope}:{rule_id}`.
5. Recompute the account cache, set `custom_loyalty_points_earned` on the invoice (`db_set`), and update campaign stats.
6. `frappe.enqueue(..., enqueue_after_commit=True)`: notification + wallet sync + tier evaluation.

A **preview** endpoint runs steps 2–3 on a draft invoice or cart without writing, for "You'll earn N points" at checkout.

### 7.3 Rules engine

`shared/loyalty/rules.py` evaluates in this order:

1. **Collect** rules from the programme's `base_rules` and from every campaign whose window, recurrence, channel, tier, segment and territory match the context, and that still has budget.
2. **Non-stackable campaigns**: keep only the highest-priority one; stackable campaigns all apply.
3. **Additive rules** (Spend Rate, Spend Threshold, Item Quantity, Item Spend, Fixed Bonus), sorted by priority. Check `min_order_amount`, `min_qty`, `order_number` and `condition`; compute points; apply `max_points_per_order`. An `exclusive` rule stops lower-priority rules in its scope (base or that campaign).
4. **Tier multiplier** applies to base points.
5. **Multiplier rules** apply to base points, or to all points so far, per `multiplier_scope`. The extra points become a separate Bonus award attributed to the campaign.
6. **Caps**: campaign `points_budget` and `per_customer_cap`, enforced under a lock on the campaign row when the award is written (only when a cap is set).
7. **Rounding** per programme.

**Custom conditions:** `frappe.safe_eval(condition, None, ctx)`. The context has only plain values (`order.total`, `order.channel`, `order.weekday`, `order.hour`, `order.items` as a list of dicts, `customer.tier`, `customer.order_count`, `customer.days_since_last_order`). There are no doc objects and no DB access. Expressions are validated on save by test-evaluating them against a sample context.

Adding a new rule type later means one function in `rules.py` registered in a `RULE_HANDLERS` dict, plus a Select option. No schema or architecture change.

### 7.4 Event-based earning

```python
loyalty.emit(event_code, customer, reference_doctype=None, reference_name=None, payload=None)
```

- It finds Event rules for `event_code` in the programme and active campaigns.
- It enforces `once_per_customer` / `cooldown_days`.
- It writes Bonus entries with key `event:{event_code}:{customer}:{reference or date}`.

Built-in emitters:

| Event | Emitted from |
| --- | --- |
| `customer_signup` | sign-up / `ensure_customer_for_user` |
| `first_order` | `award_for_invoice` when the order number is 1 |
| `birthday` | daily scheduler (needs a birth-date field; add as a custom field if absent) |
| `feedback_submitted` | `ArcPOS Feedback` `after_insert` |
| *any admin-defined code* | `api.loyalty.events.emit` (Loyalty Manager / API key) |

### 7.5 Redemption on an order (points as tender)

**Recommended model:** loyalty points are a **payment method**, not a discount.

- `discount_amount` is already owned by the promo coupon *or* gift cards (`shared/coupon/services.py:991`). A third owner would be fragile.
- Tender supports combined payment natively: points plus card/cash on the same order.
- Accounting is correct: tender debits the loyalty liability account.
- Tax treatment differs from a discount (see Open Decision D1).

Flow:

1. **Apply** (`api.loyalty.apply_points`, invoice draft, `points`). Validate:
   - the account belongs to the caller (storefront, via `shared/customer_access`), or the caller is staff
   - status Active, programme Active, channel allowed
   - `points ≥ min_redeem_points`, a multiple of `redeem_increment`, ≤ `max_redeem_points_per_order`
   - value ≤ `max_redeem_percent_of_order` × total, and value ≤ outstanding
   - points ≤ available
   - step-up OTP verified when `points > step_up_threshold_points` (staff path)

   Then set `custom_loyalty_points_redeemed` and `custom_loyalty_redeem_value`, and add or update a payments row with the loyalty Mode of Payment. Nothing is deducted yet.
2. **Validate hook** on every save re-checks the limits against the current total. If items were removed and the cap shrinks, the value is clamped and the payment row updated.
3. **`before_submit`**: lock the account, re-read available from the ledger, and fail with a clear message if it is insufficient (two drafts racing for the same points: the second fails here). Then post a `Redeem` entry (`-points`, key `redeem:{invoice}`), consuming lots **FIFO by earliest expiry**, with allocation rows. This runs inside the submit transaction, so a failed submit rolls the redemption back.
4. **Remove** (`api.loyalty.remove_points`) clears the fields and payment row on a draft.

If an order's tender is recorded by `Payment Entry` rather than the invoice payments table, the redemption posts a Payment Entry with the loyalty mode instead. Phase 0 confirms which path each channel uses (P0-2).

### 7.6 Idempotency keys

| Operation | Key |
| --- | --- |
| Earn / bonus on invoice | `earn:{invoice}:{scope}:{rule_id}` |
| Event award | `event:{code}:{customer}:{ref or yyyy-mm-dd}` |
| Redeem on invoice | `redeem:{invoice}` |
| Reward redemption | `reward:{request_id}` (client-supplied, same pattern as `Idempotency-Key`) |
| Reverse | `reverse:{original_txn}:{source}` |
| Partial return reversal | `reverse:{return_invoice}:{rule_id}` |
| Expire | `expire:{lot}` |
| Adjustment | `adjust:{adjustment}` / `adjust-cancel:{adjustment}` |

A duplicate insert hits the unique index. The service catches `frappe.UniqueValidationError` / `frappe.DuplicateEntryError` and returns the existing row (no-op).

### 7.7 Reversal: cancellations and returns

- **Invoice cancel** (`Sales Invoice.on_cancel`):
  1. Reverse every Earn/Bonus entry sourced from the invoice. Unconsumed lot parts are simply reversed. Consumed parts follow `allow_negative_balance_on_reversal`: either a negative balance that offsets future earning, or reverse only what remains and log the shortfall.
  2. Reverse the Redeem entry, restoring each allocated lot with its **original expiry**. If that expiry has passed, add a 7-day grace so the customer can use them.
  3. Return campaign budget.
- **Credit note** (`is_return = 1`, `return_against`): reverse earned points **pro rata** on the returned eligible amount, per rule, so item rules reverse only for the returned items. Restore redeemed points pro rata to the refunded amount.
- **Pending lots** are reversed for free (never spendable). This is why `pending_days` should cover the return window.

### 7.8 Scheduled jobs

| Job | When | Does |
| --- | --- | --- |
| `release_pending_points` | hourly | Pending lots with `available_on ≤ today` → Available; recompute cache; wallet sync |
| `expire_points` | daily 00:30 | Lots with `expiry_date < today` and `remaining > 0`: post an Expire entry, set the lot to Expired. Rolling-inactivity mode expires all lots of accounts inactive beyond `expiry_days` |
| `send_expiry_notices` | daily 09:00 | For each `expiry_notice_days` offset: accounts with points expiring on that date → notification (deduped via notification log); Google pass message; Apple pass field update |
| `update_campaign_status` | every 10 min | Scheduled → Active → Ended by window / recurrence; Ended when budget is exhausted |
| `review_tiers` | daily 02:00 | Rolling-window recalculation; downgrades at `tier_review_date` |
| `post_liability_true_up` | daily 23:50 / monthly | §9 |
| `reconcile_wallet_passes` | daily 03:00 | Re-render every Installed pass; push where `hash ≠ last_synced_hash` |
| `reconcile_account_cache` | weekly | Recompute every account cache from the ledger; report drift to Error Log |

All are registered under `scheduler_events` in `hooks.py`. Cron keys go into the existing shared entries where the schedule matches (see the warning in `hooks.py` about duplicate cron keys).

### 7.9 Reward redemption

`api.loyalty.redeem_reward(reward, request_id)`:

1. Lock the account, validate (cost, tier, stock, per-customer limit).
2. Post a Redeem entry (`reward:{request_id}`).
3. Create a single-use Coupon Code through the coupon engine, linked to the customer (`custom_linked_email`), with validity and the reward's discount or free item.
4. Return the code.

The voucher is then used through the existing coupon apply flow. The existing `expire_coupon_codes` job expires it, and a loyalty hook on that status change refunds unused-voucher points (configurable).

---

## 8. Customer Identification & Security

### 8.1 Member token (barcode)

The QR/barcode on passes and in-app encodes:

```
AL1.{member_number}.{token_version}.{hmac_sha256(secret, member_number|token_version)[:16]}
```

- It is not guessable and is verified server-side.
- **Reissue** bumps `token_version`, invalidating screenshots or lost passes, and pushes updated passes.
- The token **identifies**, it does not authorise. Redemption also requires either a staff session on the POS or the customer's own authenticated session.

### 8.2 Step-up verification

POS redemption above `step_up_threshold_points` sends a 6-digit OTP to the account's email/mobile (rate-limited, 5-minute TTL, stored hashed in Redis). It sets `custom_loyalty_verified` on the invoice. Redemptions below the threshold need only the scanned token.

### 8.3 Permissions

| Role | Can |
| --- | --- |
| **ArcPOS Loyalty Manager** (new, added to the fixtures role list) | Programmes, campaigns, tiers, segments, rewards, settings; approve adjustments; all reports |
| **Restaurant Cashier / ArcPOS Register User** | Look up a member, apply/remove points on an order, enrol a customer, create (not approve) adjustments |
| **ArcPOS Web Customer** | Own account only, via the APIs in §10 (never Desk) |
| Everyone | No write/delete on Transaction, ever |

All customer APIs resolve the account from the session (`customer_of(frappe.session.user)`) and **never** accept a customer id from the client. This follows `shared/customer_access.py`.

---

## 9. Accounting

- **Liability account** (`Loyalty Points Liability`, current liability) and **expense account** (`Loyalty Programme Expense`).
- **Redemption**: the loyalty Mode of Payment's default account = liability account. Points-tender on an invoice posts Dr Liability / Cr Debtors through standard ERPNext.
- **True-up Journal Entry** (daily, or monthly per settings). Target liability = (available + pending points) × `point_value`. Post Dr Expense / Cr Liability (or the reverse) for the difference against the current GL balance. The JE is linked from an `ArcPOS Loyalty Liability Run` log row (date, points, value, JE, delta).
- This avoids one JE per earn (which would mean thousands of JEs per day) while keeping the GL liability equal to the ledger at each run.
- **Breakage** (expired points) flows out automatically at the next true-up, because expired points leave the target.

> Needs accountant sign-off (D2).

---

## 10. API Design

Routes are registered like `api/gift_card/__init__.py` → `api/__init__.py` (`loyalty_api_routes`).

### 10.1 Customer (storefront / app, `ArcPOS Web Customer`)

| Route | Method | Purpose |
| --- | --- | --- |
| `api.loyalty.me` | GET | Account summary: member number, tier, next-tier progress, available/pending points + value, expiring soon (date + points), lifetime stats, pass status per platform, member token |
| `api.loyalty.enrol` | POST | Opt in (if not auto-enrolled) |
| `api.loyalty.transactions` | GET | Paginated ledger (`type`, `from`, `to` filters), each row with source label (order number), expiry, status |
| `api.loyalty.campaigns` | GET | Active campaigns the caller is eligible for (customer-facing copy only) |
| `api.loyalty.rewards` | GET | Reward catalogue with an affordability flag |
| `api.loyalty.redeem_reward` | POST | §7.9; requires `Idempotency-Key` |
| `api.loyalty.preview_earning` | POST | Points this cart/draft order would earn |
| `api.loyalty.redemption_options` | GET | For a draft order: min, max, step, value per point |
| `api.loyalty.apply_points` | POST | §7.5 |
| `api.loyalty.remove_points` | POST | §7.5 |
| `api.loyalty.preferences` | GET/POST | Notification preferences |
| `api.loyalty.wallet.google_save_url` | GET | Signed "Add to Google Wallet" URL |
| `api.loyalty.wallet.apple_pass` | GET | `.pkpass` download (`application/vnd.apple.pkpass`) |

### 10.2 Staff (POS)

| Route | Method | Purpose |
| --- | --- | --- |
| `api.loyalty.lookup` | GET | By scanned token, member number, phone or email → summary (masked PII) |
| `api.loyalty.staff_enrol` | POST | Enrol the invoice's customer |
| `api.loyalty.request_otp` / `verify_otp` | POST | Step-up (§8.2) |
| `api.loyalty.apply_points` / `remove_points` | POST | Same endpoints; staff branch |
| `api.loyalty.adjust` | POST | Creates an `ArcPOS Loyalty Adjustment` (auto-submits under the approval threshold for managers) |
| `api.loyalty.reissue_pass` | POST | Bump token, void + reissue passes |

### 10.3 Integrations

| Route | Auth | Purpose |
| --- | --- | --- |
| `api.loyalty.events.emit` | API key, `ArcPOS Loyalty Manager` | Fire any event type for a customer (requires an idempotency `reference`) |
| `/loyalty-wallet/apple/v1/...` | `ApplePass <token>` | PassKit web service (§11.3) |
| `api.loyalty.wallet.google_callback` | Google-signed callback | Save/delete notifications → pass status |

All responses follow the existing `{ success, message, data }` shape used by the gift card APIs. Errors go through `utils/error_handler.py`. Guest endpoints are covered by `utils/rate_limit.py`.

---

## 11. Wallet Integration

### 11.1 Common design

`shared/loyalty/wallet/` has a `base.py` exposing `render(account) → PassView` (balance, value, tier, member token, expiring points, programme branding, status). It also has `google.py` and `apple.py` adapters implementing `issue`, `update`, `void` and `reissue`.

- **Sync trigger**: any ledger write, tier change, account status change, programme branding change, or token reissue calls `wallet.schedule_sync(account)`.
- **Debounce**: a Redis key `loyalty:wallet-sync:{account}` with a 30-second TTL; a job is enqueued only if the key was not already set. This avoids a push storm when one order writes several entries.
- **Job**: render → hash → skip if `hash == last_synced_hash` → push to each Installed/Issued pass → on success store hash + time, on failure increment `retry_count`, store `last_error`, and re-enqueue with backoff (1 m, 5 m, 30 m, 2 h). The nightly reconcile catches anything left.
- **The pass never holds a balance of its own**. Redemption always validates against the ledger, so a stale pass cannot overspend.

### 11.2 Google Wallet

Prerequisites (lead time — start in Phase 0):

- a Google Pay & Wallet Console issuer account (publishing approval required for production)
- a GCP service account with the Wallet API enabled
- the service account added as a console user

Objects:

- **LoyaltyClass** per programme: `{issuerId}.{programme_slug}`, with `programName`, `programLogo`, `hexBackgroundColor`, `localizedRewardsTier`, links, and `callbackOptions.url` → `api.loyalty.wallet.google_callback`. Created or updated when the programme is saved.
- **LoyaltyObject** per account: `{issuerId}.{member_number}`, with:
  - `classId`, `state` (ACTIVE / INACTIVE / EXPIRED)
  - `accountId` = member number, `accountName`
  - `loyaltyPoints.balance.int`; `secondaryLoyaltyPoints` = currency value (`balance.money`)
  - `barcode` `{type: QR_CODE, value: member token}`
  - `textModulesData`: tier, pending points, next expiry
  - `messages` for expiring-soon notices
- **Save link**: an RS256 JWT signed with the service account key: `{"iss": sa_email, "aud": "google", "typ": "savetowallet", "origins": [storefront], "payload": {"loyaltyObjects": [object]}}` → `https://pay.google.com/gp/v/save/{jwt}`. The object is created on first save.
- **Updates**: `PATCH https://walletobjects.googleapis.com/walletobjects/v1/loyaltyObject/{id}` with an OAuth token from the service account (`https://www.googleapis.com/auth/wallet_object.issuer`). Google pushes to devices. `addMessage` for notifications.
- **Revocation / expiry / reissue**: `state = INACTIVE` (closed or suspended) or `EXPIRED` (programme ended); reissue patches the barcode value.
- Libraries: `google-auth` (service account credentials + token) and `requests`. PyJWT is already used in `utils/jwt_auth.py`.

### 11.3 Apple Wallet

Prerequisites (lead time):

- Apple Developer Program membership
- a **Pass Type ID** (e.g. `pass.com.arcpos.loyalty`) and its signing certificate (.p12)
- the Apple WWDR G4 intermediate certificate

**Pass generation** (`storeCard` style):

- `pass.json` fields:
  - `formatVersion`, `passTypeIdentifier`, `teamIdentifier`
  - `serialNumber` = member number, `organizationName`, `description`
  - colours, `logoText`
  - `barcodes` `[{format: PKBarcodeFormatQR, message: member token, messageEncoding: iso-8859-1}]`
  - `storeCard`: `primaryFields` points; `secondaryFields` value + tier; `auxiliaryFields` expiring points + date; `backFields` terms + benefits
  - `authenticationToken` (random 32 bytes, stored **hashed**), `webServiceURL` = `apple_web_service_url`
  - `voided` when closed; `expirationDate` when the programme ends
- `changeMessage` on fields (e.g. `"You now have %@ points"`) gives lock-screen notifications on updates.
- `manifest.json` (SHA-1 of every file) → `signature`: a detached PKCS#7 signature (`cryptography` `pkcs7.PKCS7SignatureBuilder`, signer = pass cert + key, plus the WWDR cert, `DetachedSignature` + `Binary` options) → zip → `.pkpass`.

**PassKit web service** (Apple appends these paths to `webServiceURL`):

| Method & path | Does |
| --- | --- |
| `POST /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}/{serialNumber}` | Register device + `pushToken` (201 new / 200 existing) |
| `DELETE /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}/{serialNumber}` | Unregister |
| `GET /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}?passesUpdatedSince={tag}` | Serials changed since tag (`lastUpdated` = sync timestamp) or 204 |
| `GET /v1/passes/{passTypeIdentifier}/{serialNumber}` | Latest `.pkpass`; honour `If-Modified-Since` → 304 |
| `POST /v1/log` | Device error logs → Error Log |

The auth header is `Authorization: ApplePass {authenticationToken}`, compared in constant time against the stored hash.

**Routing in Frappe:** these are REST paths with path parameters and DELETE, which `/api/method` cannot express. Plan:

- **Primary:** a custom `page_renderer` hook whose `can_render()` matches the `loyalty-wallet/apple/` prefix and returns raw `Response` objects with exact status codes.
- **Fallback:** an nginx `location` rewrite to `/api/method/...` with the path parts as query args.
- Spike P0-3 picks one. It must also verify that CSRF, the `before_request` guest rate limiter and Turnstile do not interfere (these endpoints are guest + token auth).

**Push updates:** APNs HTTP/2 to `api.push.apple.com:443` (or the sandbox host), authenticated with the **Pass Type ID certificate**. The topic is `passTypeIdentifier`, the payload `{}`, one push per registered device. A 410 response deletes the registration. Library: `httpx[http2]` (new dependency).

**Revoke / reissue:** set `voided: true` and push (closed account); reissue = new token version + push (the serial stays the same).

### 11.4 Redemption through wallets

- Staff scan the pass QR at the POS → `api.loyalty.lookup` → apply points (§7.5).
- Online, the app shows the same token and redemption happens in-app.
- Wallets never redeem on their own. This satisfies "compatible wallet-based experiences" without the wallet keeping its own balance.

---

## 12. Notifications

| Event | Channel | Notes |
| --- | --- | --- |
| Points earned | Email + push | One message per invoice |
| Points available (pending released) | Push | Optional |
| Points redeemed | Email + push | Receipt-like |
| Expiring soon | Email + push + Google pass message + Apple `changeMessage` | Per `expiry_notice_days`; deduped |
| Tier up / down | Email + push + pass update | |
| Reward voucher issued | Email | With coupon code |

- Templates follow `shared/email_templates/get_template.py`.
- Push uses whichever channel reaches *customers*. `api/web_push` covers storefront browsers; Expo via `api/notification` targets staff roles today, so a customer path must be confirmed in P0-4.
- Each send is recorded in `ArcPOS Loyalty Notification Log` (account, kind, key, sent_at) to prevent duplicates.

---

## 13. Administration (Desk)

- **Workspace "Loyalty"**: Programmes, Campaigns, Accounts, Transactions, Adjustments, Rewards, Segments, Event Types, Settings, Reports.
- **Number cards**: active members, outstanding points, outstanding liability value, points earned / redeemed / expired this month, active campaigns.
- **Charts**: points earned vs redeemed vs expired (monthly), campaign points issued.
- **Campaign form actions**: Activate, Pause, Resume, End, Duplicate, "Simulate on order…" (runs the rules engine against a chosen invoice and shows the awards).
- **Account form**: ledger timeline, Adjust, Suspend/Reactivate, Reissue Pass, Recompute Balance.
- **Script Reports** (`excel_restaurant_pos/report/`):

| Report | Content |
| --- | --- |
| Loyalty Points Summary | Earned / bonus / redeemed / expired / reversed / adjusted by period, programme, campaign, channel |
| Loyalty Liability | Outstanding points and value; ageing by expiry bucket (≤30, 31–90, 91–180, >180 days); reconciles against the GL liability balance |
| Campaign Performance | Points issued, budget used, participants, orders, revenue of qualifying orders, average order value vs non-campaign orders in the same window |
| Customer Loyalty Balances | Per account: tier, available, pending, lifetime stats, last activity |
| Redemption Activity | Redemptions by channel / outlet / staff user, rewards redeemed |
| Expiry Forecast | Points expiring per future week/month |
| Adjustment Audit | Every adjustment with requester, approver, reason |

Heavy aggregates may use stored procedures, following `report_sql/` + `shared/sql_procedures/sync`.

---

## 14. Module & File Layout

```
excel_restaurant_pos/
  shared/loyalty/
    __init__.py            # public facade: enrol, emit, award_for_invoice, schedule_sync
    settings.py            # cached settings + active programme
    ledger.py              # post(), lock_account(), recompute_cache(), FIFO allocation, idempotent insert
    accounts.py            # enrol, status changes, member token, segment/tier lookup
    rules.py               # context builder + RULE_HANDLERS + evaluate()
    earning.py             # award_for_invoice, preview
    events.py              # emit + built-in emitters
    redemption.py          # validate/apply/remove/before_submit redeem; limits
    reversal.py            # cancel + credit note logic
    expiry.py              # release pending, expire, notices
    tiers.py               # evaluate / review
    rewards.py             # reward redemption → coupon
    accounting.py          # liability true-up JE
    notifications.py
    otp.py                 # step-up verification
    wallet/
      base.py  google.py  apple.py  apple_webservice.py  sync.py
    test_*.py              # per module
  api/loyalty/
    __init__.py            # loyalty_api_routes
    customer.py  staff.py  events.py  wallet.py
  excel_restaurant_pos/doctype/arcpos_loyalty_*/   # §5 doctypes
  excel_restaurant_pos/report/loyalty_*/
  excel_restaurant_pos/workspace/loyalty/
  patches/v1_12_0/
    create_loyalty_mode_of_payment.py
    hide_native_loyalty_fields.py
docs/
  loyalty-programme-implementation-plan.md   # this file
  loyalty-api.md                             # API contract
  loyalty-frontend-guide.md                  # pos-web + order-web integration guide
```

**Hooks added to `custom_doc_events`** (`doc_event/__init__.py`):

| DocType | Event | Handler |
| --- | --- | --- |
| Sales Invoice | `validate` | `loyalty.disable_native_loyalty`; `loyalty.redemption.validate_invoice_redemption` (after the gift card hooks, before `validate_non_zero_grand_total`) |
| Sales Invoice | `before_submit` | `loyalty.redemption.post_redemption` |
| Sales Invoice | `on_submit` | `loyalty.earning.on_invoice_submit`; `loyalty.reversal.on_return_submit` (credit notes) |
| Sales Invoice | `on_cancel` | `loyalty.reversal.on_invoice_cancel` |
| Payment Entry | `on_submit` | `loyalty.earning.on_payment_settled` |
| Customer | `after_insert` | `loyalty.accounts.maybe_enrol` (respecting settings) |
| ArcPOS Feedback | `after_insert` | `loyalty.events.on_feedback` |
| Coupon Code | `on_update` | `loyalty.rewards.on_voucher_status_change` (refund unused expired vouchers) |
| ArcPOS Loyalty Programme / Campaign | `on_update` | wallet class sync, cache bust |

**New dependencies** (`pyproject.toml` / `requirements.txt`): `google-auth`, `httpx[http2]`. `cryptography` and `PyJWT` are already present through Frappe.

---

## 15. Implementation Phases

### Phase 0 — Decisions & spikes (start wallet account sign-ups on day 1)

- **P0-1** Sign off the open decisions in §17.
- **P0-2** Confirm how each channel records tender (invoice `payments` with `is_pos` vs Payment Entry) and where loyalty tender plugs in. This covers POS register, storefront, table QR, Clover, Uber Eats / DoorDash (third-party orders: no earn/redeem by default).
- **P0-3** Spike the Apple web service routing (`page_renderer` vs nginx rewrite), including the CSRF / rate-limit / Turnstile interaction.
- **P0-4** Confirm the customer push channel (web push / Expo app).
- **P0-5** Apply for a Google Wallet issuer account and an Apple Pass Type ID + certificates.

### Phase 1 — Ledger, accounts, base earning, reversal

DocTypes (Settings, Programme, Account, Transaction, Allocation, Rule, Rule Item, Tier), `ledger.py` with idempotency + locking + FIFO, enrolment (sign-up + first order + admin), base Spend Rate earning on paid invoices, Pending period, cancel + credit-note reversal, disabling native loyalty, patches, and the Account Desk form.
**Exit:** a paid POS order earns points exactly once (including under retries); cancel reverses them; the cache equals the ledger.

### Phase 2 — Redemption

Mode of Payment + accounts, apply/remove/validate/before_submit, limits, channel gates, concurrency guard, staff lookup + member token + OTP step-up, the liability true-up JE.
**Exit:** combined points + card payment works; two concurrent submits cannot overspend; the GL liability equals the ledger after a true-up.

### Phase 3 — Expiry, notifications, tiers

Expiry jobs (lot + rolling modes), expiring-soon notices, notification log, tiers + tier history + review job, earn/redeem/tier notifications.

### Phase 4 — Rules engine & campaigns

Campaign, Segment and Event Type DocTypes; all rule types; stacking/exclusive/caps/budget; safe_eval conditions; event emitter + built-in events + events API; campaign scheduler; "Simulate on order"; preview earning.

### Phase 5 — Admin & reporting

Adjustment doctype + workflow, workspace, number cards, charts, the 7 reports, Reward catalogue + reward redemption → coupon.

### Phase 6 — Customer APIs & frontend guide

All §10.1 / §10.2 endpoints, `docs/loyalty-api.md`, `docs/loyalty-frontend-guide.md` (screens: loyalty home, history, campaigns, rewards, checkout redemption, POS lookup/scan, Add to Wallet buttons).

### Phase 7 — Google Wallet

Class/object rendering, save link, callbacks, patch updates, messages, state changes, sync/debounce/retry/reconcile.

### Phase 8 — Apple Wallet

pkpass build + signing, web service, device registrations, APNs push, void/reissue, reconcile.

### Phase 9 — Hardening & rollout

Load test (concurrent redemptions and order bursts), cache-drift reconciliation, backfill decision (D5), go-live with `enabled = 0` → enable per programme, monitoring (Error Log alerts on wallet sync failures and drift).

---

## 16. Test Plan (acceptance)

Unit tests use `FrappeTestCase` next to each module (`shared/loyalty/test_*.py`), the same pattern as `shared/gift_card/test_gift_card_services.py`.

### Ledger & safety
- [ ] The same invoice submitted/settled twice, or the hook run twice → points awarded once
- [ ] Two concurrent `before_submit` redemptions on one account with points for only one → exactly one succeeds
- [ ] A ledger row cannot be edited or deleted by any role, including System Manager through the UI
- [ ] Weekly reconcile finds no drift after a randomized sequence of earn/redeem/cancel/expire

### Earning
- [ ] Spend Rate with each rounding mode; tax excluded under Net Total basis
- [ ] Excluded item groups and gift card items earn nothing; loyalty-paid portion excluded by default
- [ ] Item / item group / brand / quantity rules award only for matching lines
- [ ] A spend threshold awards once at ≥ X
- [ ] Multiplier campaign doubles base points only (scope = base)
- [ ] Non-stackable: only the highest-priority campaign applies; exclusive rule stops lower ones
- [ ] Campaign budget and per-customer cap enforced under concurrency
- [ ] Recurring (weekday) and seasonal windows respected, including timezone boundaries
- [ ] A `safe_eval` condition with an invalid expression is rejected on save; DB access in an expression is impossible
- [ ] Sign-up event awards the configured points once per customer; first-order event fires once
- [ ] Excluded (walk-in) customer never earns

### Redemption
- [ ] Min, max, increment and % cap enforced; clamped when the order total drops
- [ ] Channel gate enforced
- [ ] Points + card on one order; invoice outstanding correct; GL Dr liability
- [ ] Storefront user cannot redeem another customer's points (resolved from session)
- [ ] OTP required above the threshold at POS
- [ ] FIFO by earliest expiry; allocations recorded

### Reversal
- [ ] Cancel: earn reversed, redeemed points restored with original expiry (+ grace if past)
- [ ] Partial credit note: pro rata per rule; item rules reverse only for returned items
- [ ] Spent points + refund honour `allow_negative_balance_on_reversal`

### Expiry & tiers
- [ ] Lot expiry posts Expire entries; rolling-inactivity mode expires all lots
- [ ] Expiry notices sent once per offset
- [ ] Pending released on `available_on`; pending not spendable
- [ ] Tier upgrade immediately; downgrade only at review; multiplier applied

### Wallets
- [ ] Google: save-link JWT valid; object patched on balance change within the debounce window; INACTIVE on close
- [ ] Apple: pkpass verifies (signature, manifest); the device registers; an update triggers APNs and the device GET returns the new pass; 304 when unchanged; `voided` on close; wrong `ApplePass` token → 401
- [ ] Reissue invalidates the old barcode at POS lookup
- [ ] Sync failure retries with backoff and the nightly reconcile fixes the pass

### Regression
- [ ] Promo coupon and gift card flows unchanged (existing tests green)
- [ ] `validate_non_zero_grand_total` still correct with points tender
- [ ] With `enabled = 0` there is no behavioural change anywhere

---

## 17. Open Decisions (recommended default in **bold**)

| # | Decision | Options |
| --- | --- | --- |
| D1 | Redemption model and tax | **Tender (payment method); tax computed on the full order** · Discount (reduces taxable amount; needs coexistence with coupon/gift card `discount_amount`) |
| D2 | Liability accounting | **Daily true-up JE** · Per-transaction JE · No GL (report only) |
| D3 | When points are earned | **When fully paid, Pending for N days** (N = return window) · On submit |
| D4 | Combine with promo coupon / gift card on the same order | **Allowed** (points apply to the remaining amount) · Mutually exclusive |
| D5 | Historical backfill | **No backfill; optional one-time welcome bonus via Adjustment import** · Award points for the last N months of orders |
| D6 | Third-party channel orders (Uber Eats, DoorDash) | **No earn, no redeem** · Earn only |
| D7 | Point value and base rate | e.g. **1 pt per 1 unit spent, 1 pt = 0.01** (1% back) — business to confirm |
| D8 | Default expiry | **12 months per lot, notices at 30/7/1 days** · Rolling 12-month inactivity |
| D9 | Step-up OTP threshold at POS | **Off at launch; configurable** |
| D10 | Apple routing | **`page_renderer` hook** · nginx rewrite (decided by spike P0-3) |

---

## 18. Risks

| Risk | Mitigation |
| --- | --- |
| Wallet issuer approvals and certificates delay launch | Start P0-5 immediately; phases 1–6 do not depend on wallets |
| Double issuance from multiple hooks (submit + payment) | Deterministic idempotency keys + unique index (§7.6) |
| Hot-row contention on popular campaign budgets | Budget check uses a short `FOR UPDATE` on the campaign row only when a budget is set |
| Push storms (many entries per order) | 30 s debounce + payload hash skip |
| Rules misconfiguration giving away points | Campaign simulation, budget caps, Draft → Active review, Points Summary alerts on spikes |
| Native ERPNext loyalty accidentally re-enabled | `validate` forces `dont_create_loyalty_points = 1`; a patch checks no active `Loyalty Program` is linked |
| Frontends live in other repos | API contract doc + frontend guide delivered in Phase 6; versioned response shapes |

---

## 19. Approval

| Role | Name | Date | Decision |
| --- | --- | --- | --- |
| Product owner | | | |
| Finance (D1, D2) | | | |
| Tech lead | | | |
