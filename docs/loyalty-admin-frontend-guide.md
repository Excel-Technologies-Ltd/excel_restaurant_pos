# Loyalty admin — POS web implementation guide

Build the loyalty setup screens in pos-web from this document. The backend is
already implemented. Do not invent endpoints or fields.

Contract summary: `docs/loyalty-api.md` (section "Programme admin").
Till screens (lookup, enrol, apply points, OTP) stay as they are in
`docs/loyalty-frontend-guide.md`. This guide is only the admin area.

## Who can open it

Show the admin area only when the signed-in user has **ArcPOS Loyalty Manager**
or **System Manager**. Anyone else gets 403 `You are not permitted to manage
the loyalty programme.` Hide the menu for cashiers, waiters, and register users.

Use the same auth header the rest of pos-web already sends. A 401 means refresh
the session and retry. Show `ValidationError` text as-is. It is written for the user.

## Calling the API

Every route is:

```
/api/method/<route>
```

Success body (Frappe wraps the payload in `message`):

```json
{
  "message": {
    "success": true,
    "message": "Programme created",
    "data": {},
    "page": 1,
    "page_size": 20,
    "total": 0
  }
}
```

`page`, `page_size`, and `total` are present on lists only. `page_size` max is 100.

POST bodies: send the fields as a JSON object in `data`, or as top-level form
fields. Child tables are JSON arrays.

```json
{
  "data": {
    "programme_name": "Spring Rewards",
    "company": "Spring Sushi",
    "point_value": 0.01,
    "status": "Draft"
  }
}
```

Rules the UI must follow:

- Send only fields the user changed on update, plus `name`. Unknown keys are ignored.
- A child table in the body **replaces the whole table**. Load the document, edit the array, send the full array back. Omitting the key leaves the table unchanged.
- Checks are `0` or `1`. Dates are `YYYY-MM-DD`. Datetimes are `YYYY-MM-DD HH:MM:SS`.
- Link fields are the document **name** (for example `CUST-00003`, not the title).
- Do not send or display `member_token_secret`, `google_callback_secret`, or `apple_pass_certificate_password`. The API never returns them.
- There is no status called Inactive. Programme `inactive` is stored as **Paused**. Account `inactive` is stored as **Suspended**.

## Screens to build

Build them in this order.

1. **Programmes** — list, create, edit, set status.
2. **Settings** — one form. Pick the active programme, then enable loyalty.
3. **Accounts** — list, detail, suspend / reactivate / close.
4. **Transactions** — list and detail. Read only.
5. **Adjustments** — list, detail, approve, reject. Create still uses `POST api.loyalty.adjust`.
6. **Campaigns** — list, create, edit, activate / pause / resume / end.
7. **Rewards** — list, create, edit.
8. **Segments** and **Event types**.
9. **Tier changes** — a read-only tab on the account. No create button.

## Programmes

| Action | Call |
| --- | --- |
| List | `GET api.loyalty.programmes?status=&company=&page=1&page_size=20` |
| Open | `GET api.loyalty.programme?name=<name>` |
| Create | `POST api.loyalty.programme.create` |
| Save | `POST api.loyalty.programme.update` with `name` |
| Status button | `POST api.loyalty.programme.set_status` with `name` and `status` |

List columns: `programme_name`, `company`, `status`, `start_date`, `end_date`, `point_value`.

`status` filter and the status button accept `Draft`, `Active`, `Paused`, `Ended`.
The button label for Paused can say "Pause". Sending `inactive` also pauses.
Only one programme per company may be Active. If another is Active, show the server error and do not switch locally.

`currency` comes back on the document and is read-only (taken from the company). Do not send it.

### Programme fields

| Field | Type | Required | Values / notes |
| --- | --- | --- | --- |
| `programme_name` | text | yes | Unique |
| `company` | link Company | yes | |
| `status` | select | yes | `Draft` (default), `Active`, `Paused`, `Ended` |
| `start_date` | date | yes | Default today. End cannot be before start |
| `end_date` | date | no | |
| `points_rounding` | select | no | `Floor` (default), `Round`, `Ceil` |
| `earn_basis` | select | no | `Net Total (excl. tax)` (default), `Grand Total` |
| `earn_on` | select | no | `Paid` (default), `Submitted` |
| `pending_days` | int | no | Days before earned points can be spent. `0` = immediately |
| `exclude_gift_card_items` | check | no | Default `1` |
| `earn_on_loyalty_paid_amount` | check | no | Default `0` |
| `exclude_item_groups` | table | no | Rows: `{ "item_group": "<Item Group name>" }` |
| `earn_dine_in` | check | no | Dine-in / takeout. Default `1` |
| `earn_in_store_pickup` | check | no | Default `1` |
| `earn_online_delivery` | check | no | Default `1` |
| `earn_online_pickup` | check | no | Default `1` |
| `point_value` | currency | yes | What 1 point is worth. Must be > 0. `0.01` means 100 points = 1.00 |
| `min_redeem_points` | int | no | Default `0` |
| `max_redeem_points_per_order` | int | no | `0` = no cap |
| `max_redeem_percent_of_order` | percent | no | `1`–`100`. Default `100`. At 100, points may round up to cover the bill |
| `redeem_increment` | int | no | Spend in multiples of this. Default `1`. Values under 1 are saved as 1 |
| `allow_negative_balance_on_reversal` | check | no | Default `0` |
| `restore_grace_days` | int | no | Default `7` |
| `redeem_dine_in` | check | no | Default `1` |
| `redeem_in_store_pickup` | check | no | Default `1` |
| `redeem_online_delivery` | check | no | Default `1` |
| `redeem_online_pickup` | check | no | Default `1` |
| `expiry_mode` | select | no | `Fixed Days per Lot` (default), `Rolling Inactivity`, `Never` |
| `expiry_days` | int | when mode is not Never | Default `365`. Required and > 0 unless mode is Never |
| `expiry_notice_days` | text | no | Comma-separated numbers, e.g. `30,7,1` |
| `tier_basis` | select | no | `Lifetime Spend` (default), `Rolling 12-Month Spend`, `Rolling 12-Month Points` |
| `tier_review` | select | no | `Upgrade Immediately, Downgrade at Review` (default), `Continuous`, `Immediate Upgrade & Downgrade` |
| `tiers` | table | no | See tier row |
| `base_rules` | table | no | See rule row |
| `base_rule_items` | table | no | See rule item row. Only when a rule's `applies_to` is `Filtered` |
| `terms` | HTML | no | Shown on the wallet pass |

### Tier row (`tiers`)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `tier_name` | text | yes | Unique inside the programme |
| `rank` | int | yes | `1` = lowest. Ranks must be unique |
| `threshold` | number | no | Measured with `tier_basis` |
| `earn_multiplier` | number | no | Default `1`. Values ≤ 0 are saved as 1 |
| `benefits` | text | no | Shown on the pass |
| `pass_color` | hex colour | no | e.g. `#1F2937`. Falls back to settings background |

### Rule row (`base_rules` and campaign `rules`)

| Field | Type | Required | Values / notes |
| --- | --- | --- | --- |
| `rule_name` | text | yes | |
| `rule_id` | text | no | Leave empty on create. The server assigns 8 characters. To attach items, put the **rule name** in the item's `rule_id`; the server swaps it |
| `enabled` | check | no | Default `1` |
| `trigger` | select | no | `Purchase` (default), `Event` |
| `event_type` | link ArcPOS Loyalty Event Type | when trigger is Event | The event code, e.g. `birthday` |
| `rule_type` | select | yes | `Spend Rate`, `Spend Threshold`, `Item Quantity`, `Item Spend`, `Fixed Bonus`, `Multiplier` |
| `points` | int | for Fixed Bonus / thresholds | Points awarded, or points per step |
| `per_amount` | currency | for Spend Rate and Item Spend | Must be > 0. "1 point per this much spend" |
| `multiplier` | number | for Multiplier | Must be > 1 |
| `multiplier_scope` | select | no | `Base Points` (default), `All Points Before Multipliers` |
| `applies_to` | select | no | `All Items` (default), `Filtered` |
| `min_order_amount` | currency | no | |
| `min_qty` | number | no | |
| `order_number` | int | no | Award only on that order number (1 = first order) |
| `max_points_per_order` | int | no | `0` = no cap |
| `priority` | int | no | Higher runs first. Default `0` |
| `exclusive` | check | no | When this rule awards, lower-priority rules in the same programme or campaign are skipped |
| `condition` | text | no | Optional safe expression. Leave blank in the first version of the UI |

`Spend Rate` example: `per_amount` 1.00 and `points` 1 awards 1 point per 1.00 of the earn basis.

### Rule item row (`base_rule_items` and campaign `rule_items`)

| Field | Type | Required | Values |
| --- | --- | --- | --- |
| `rule_id` | text | yes | The rule's `rule_id`, or its `rule_name` on the same save |
| `applies_to` | select | yes | `Item`, `Item Group`, `Brand` |
| `value` | text | yes | Item code, item group name, or brand |

## Settings

One record for the whole site. No create button.

| Action | Call |
| --- | --- |
| Load | `GET api.loyalty.settings.get` |
| Save | `POST api.loyalty.settings.update` |

Do not enable loyalty until `active_programme` is an **Active** programme. The server refuses `enabled = 1` with no programme. If the chosen programme is Draft, Paused, or Ended, loyalty stays on but nothing is earned or redeemed. Show that warning.

Saving `liability_account` also points the Loyalty Points mode of payment at that account. Do not build a separate mode-of-payment screen.

Certificate files (`apple_pass_certificate`, `apple_wwdr_certificate`, `google_service_account_json`) must already be private files (`/private/files/...`). The POS form can show the current file name. Uploading a new certificate can stay on Desk for the first version. Do not add password inputs.

### Settings fields

| Field | Type | Notes |
| --- | --- | --- |
| `enabled` | check | Master switch |
| `active_programme` | link ArcPOS Loyalty Programme | |
| `auto_enrol_on_signup` | check | |
| `auto_enrol_on_first_order` | check | |
| `excluded_customers` | table | Rows: `{ "customer": "<Customer name>" }`. Walk-in customers belong here |
| `adjustment_approval_threshold` | int | Absolute points above this need a second Loyalty Manager. `0` = no threshold |
| `step_up_threshold_points` | int | Till asks for an OTP above this many points. `0` = off |
| `refund_expired_vouchers` | check | Return points when a reward voucher expires unused |
| `notify_email` | check | Default for new members |
| `notify_push` | check | Default for new members |
| `loyalty_mode_of_payment` | link Mode of Payment | Usually `Loyalty Points` |
| `liability_account` | link Account | Must belong to the programme company |
| `expense_account` | link Account | Same company |
| `cost_center` | link Cost Center | |
| `liability_true_up_frequency` | select | `Daily`, `Monthly`, `Off`. Use Daily when points can cover a whole bill |
| `voucher_pricing_rule` | link Pricing Rule | Required before rewards can be redeemed |
| `email_template_earned` | link Email Template | |
| `email_template_redeemed` | link Email Template | |
| `email_template_expiring` | link Email Template | |
| `email_template_tier` | link Email Template | |
| `email_template_voucher` | link Email Template | |
| `email_template_otp` | link Email Template | |
| `google_enabled` | check | |
| `google_issuer_id` | text | |
| `google_class_suffix` | text | Optional |
| `google_origins` | text | One origin per line, e.g. `https://order.example.com` |
| `google_service_account_json` | private file URL | Display only in v1 |
| `apple_enabled` | check | |
| `apple_pass_type_id` | text | e.g. `pass.com.excel.arcpos.loyaltycard` |
| `apple_team_id` | text | |
| `apple_organization_name` | text | |
| `apple_web_service_url` | text | Must be the Frappe site: `https://<frappe-host>/loyalty-wallet/apple`. Not the order website |
| `apple_apns_environment` | select | `Production` (default), `Sandbox` |
| `apple_pass_certificate` | private file URL | Display only in v1 |
| `apple_wwdr_certificate` | private file URL | Display only in v1 |
| `programme_display_name` | text | Name printed on the pass. Falls back to the programme name |
| `pass_logo` | image URL | |
| `pass_icon` | image URL | Required before an Apple pass can be issued. PNG |
| `pass_strip_image` | image URL | |
| `pass_background_color` | hex colour | |
| `pass_foreground_color` | hex colour | |
| `pass_label_color` | hex colour | |

## Accounts

| Action | Call |
| --- | --- |
| List | `GET api.loyalty.accounts?status=&programme=&query=&page=1&page_size=20` |
| Open | `GET api.loyalty.account?name=<member number>` |
| Change status | `POST api.loyalty.account.set_status` with `name`, `status`, `remarks` |

`query` matches member number, customer name, or customer id.
`status` filter: `Active`, `Suspended`, `Closed`. `inactive` filters as Suspended.

List columns: `member_number`, `customer_name`, `status`, `tier`, `available_points`, `pending_points`, `programme`.

Detail `data` is the member summary (same numbers as the till) plus:

| Field | Meaning |
| --- | --- |
| `name` | Member number. This is the id to pass back |
| `customer` | Customer id |
| `programme_id` | Programme document name |
| `enrolment_source` | How they joined |
| `order_count` | |
| `qualifying_value` | Value used for the tier |
| `available_points`, `pending_points`, `tier`, `tier_progress`, `expiring`, `lifetime`, `wallet`, `preferences` | Display only |

Status actions:

- Active → Suspended (`inactive` is accepted).
- Suspended → Active.
- Active or Suspended → Closed. Ask for confirmation. Remaining points expire. A closed account cannot be reopened.

Do not put a "delete account" button on the screen.

## Transactions

Read only. No create, edit, or delete.

| Action | Call |
| --- | --- |
| List | `GET api.loyalty.transactions.list` |
| Open | `GET api.loyalty.transaction?name=` |

Query params: `account`, `customer`, `programme`, `type`, `status`, `from_date`, `to_date`, `page`, `page_size`.

`type` is a comma-separated list of `Earn`, `Bonus`, `Redeem`, `Expire`, `Reverse`, `Adjust`.
`status` is `Pending`, `Available`, `Consumed`, `Expired`, `Reversed`.

List and detail fields:

| Field | Meaning |
| --- | --- |
| `name` | e.g. `LTX-2026-000000001` |
| `account` | Member number |
| `customer` | Customer id |
| `programme` | Programme name |
| `posting_datetime` | |
| `transaction_type` | One of the types above |
| `points` | Signed. Show positive in green and negative in red |
| `status` | |
| `currency_value` | Money value of the points |
| `available_on` | When a pending earn becomes spendable |
| `expiry_date` | |
| `remaining_points` | Still unspent on this lot |
| `source_doctype` | `Sales Invoice`, `ArcPOS Loyalty Adjustment`, `Coupon Code`, … |
| `source_name` | Document name. Link the invoice when the doctype is Sales Invoice |
| `source_label` | Ready-made label, e.g. `Order SINV-…` |
| `campaign` | Campaign id, when the points came from one |
| `event_type` | Event code, when the points came from an event |
| `remarks` | |

Detail also includes `basis_amount`, `basis_qty`, `basis_items`, and `allocations`. Show them as a read-only breakdown. Do not post them back.

To correct points, call the existing till route, not a transaction write:

`POST api.loyalty.adjust` with `account`, `points` (signed; negative removes), `reason`, `remarks` (required), `expiry_date` (optional, credits only).

`reason`: `Goodwill` (default), `Correction`, `Promotion`, `Migration`, `Other`.

## Adjustments

| Action | Call |
| --- | --- |
| List | `GET api.loyalty.adjustments?account=&approval_status=&page=1&page_size=20` |
| Open | `GET api.loyalty.adjustment?name=` |
| Approve and post | `POST api.loyalty.adjustment.approve` with `name` |
| Reject | `POST api.loyalty.adjustment.reject` with `name` and `reason` |

`approval_status`: `Draft`, `Pending Approval`, `Approved`, `Rejected`.

Show Approve only when `docstatus` is `0` and status is Draft or Pending Approval.
A large adjustment (`requires_approval = 1`) must be approved by a Loyalty Manager who did not request it. The server enforces that. Show the error if the same user tries.

Detail fields worth showing: `account`, `customer`, `customer_name`, `points`, `reason`, `remarks`, `expiry_date`, `approval_status`, `requires_approval`, `requested_by`, `approved_by`, `approved_on`, `rejection_reason`, `transaction` (link to the ledger row after posting).

## Campaigns

| Action | Call |
| --- | --- |
| List | `GET api.loyalty.campaigns.list?programme=&status=&page=1&page_size=20` |
| Open | `GET api.loyalty.campaign?name=` |
| Create | `POST api.loyalty.campaign.create` |
| Save | `POST api.loyalty.campaign.update` with `name` |
| Lifecycle | `POST api.loyalty.campaign.action` with `name` and `action` |

Do not send `status` on create or update. New campaigns are Draft. Change status only with `action`:

| Action | From | Result |
| --- | --- | --- |
| `activate` | Draft | `Scheduled` if start is in the future, otherwise `Active` |
| `pause` | Active or Scheduled | `Paused` |
| `resume` | Paused | `Scheduled` or `Active` |
| `end` | any except Ended | `Ended` |

`activate` and `resume` fail with no rules. Pause a live campaign before saving rule changes. The server rejects an edit of rules, rule items, while status is Active.

`points_issued`, `participants`, and `orders` are read-only stats. Show them. Do not send them.

Customer-facing campaigns are `GET api.loyalty.campaigns` (no `.list`). Do not use that route on this screen.

### Campaign fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `campaign_name` | text | yes | |
| `programme` | link programme | yes | An Ended programme is refused |
| `priority` | int | no | Default `0` |
| `stackable` | check | no | Default `1` |
| `display_in_app` | check | no | Default `1`. Off hides it from the customer app |
| `start_datetime` | datetime | yes | |
| `end_datetime` | datetime | required for Yearly | Cannot be before start |
| `recurrence` | select | no | `None` (default), `Weekly`, `Yearly` |
| `recurrence_days` | text | required for Weekly | Weekday names, e.g. `Fri,Sat` |
| `recurrence_start_time` | time | no | `HH:MM:SS` |
| `recurrence_end_time` | time | no | |
| `recur_until` | date | no | |
| `eligible_dine_in` | check | no | Default `1` |
| `eligible_in_store_pickup` | check | no | Default `1` |
| `eligible_online_delivery` | check | no | Default `1` |
| `eligible_online_pickup` | check | no | Default `1` |
| `eligible_tiers` | text | no | Comma-separated tier names. Empty = all tiers |
| `eligible_segments` | table | no | Rows: `{ "segment": "<segment name>" }` |
| `eligible_territories` | table | no | Rows: `{ "territory": "<Territory name>" }` |
| `points_budget` | int | no | `0` = no budget. The campaign ends when issued points reach it |
| `per_customer_cap` | int | no | `0` = no cap |
| `rules` | table | required before activate | Same columns as programme base rules |
| `rule_items` | table | no | Same columns as programme base rule items |
| `title` | text | no | Card title in the app. Falls back to `campaign_name` |
| `image` | image URL | no | |
| `description` | text | no | |

## Rewards

| Action | Call |
| --- | --- |
| List | `GET api.loyalty.rewards.list?programme=&enabled=&page=1&page_size=20` |
| Open | `GET api.loyalty.reward?name=` |
| Create | `POST api.loyalty.reward.create` |
| Save | `POST api.loyalty.reward.update` with `name` |

`enabled` filter is `1` or `0`. `redeemed_count` is read-only.

Customer redemption stays on `GET api.loyalty.rewards` and `POST api.loyalty.redeem_reward`. This screen only edits the catalogue.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `reward_name` | text | yes | |
| `programme` | link programme | yes | |
| `enabled` | check | no | Default `1` |
| `reward_type` | select | no | `Order Discount Voucher` (default), `Free Item` |
| `points_cost` | int | yes | Must be > 0 |
| `image` | image URL | no | |
| `description` | text | no | |
| `discount_type` | select | for a discount voucher | `Flat Amount` (default), `Percentage` |
| `discount_value` | number | for a discount voucher | Must be > 0. Percentage cannot exceed 100 |
| `max_discount_amount` | currency | no | Cap on a percentage voucher |
| `free_item` | link Item | for Free Item | Voucher equals the item price and only applies on orders that contain it |
| `voucher_validity_days` | int | no | Default `30` |
| `redemption_allow_on` | select | no | `All` (default), `POS`, `Dine-in`, `In Store Pickup`, `Online Pickup`, `Online Delivery`, `Only Online` |
| `min_order_amount` | currency | no | |
| `eligible_tiers` | text | no | Comma-separated tier names. Empty = all |
| `stock_limit` | int | no | `0` = unlimited |
| `per_customer_limit` | int | no | `0` = unlimited |
| `active_from` | date | no | |
| `active_to` | date | no | Cannot be before `active_from` |

Settings must have `voucher_pricing_rule` or redemption fails later. The reward form does not need to set it.

## Segments

| Action | Call |
| --- | --- |
| List | `GET api.loyalty.segments?page=1&page_size=20` |
| Open | `GET api.loyalty.segment?name=` |
| Create | `POST api.loyalty.segment.create` |
| Save | `POST api.loyalty.segment.update` with `name` |

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `segment_name` | text | yes | |
| `match_mode` | select | no | `Filters`, `Static Members`, `Filters or Static Members` |
| `description` | text | no | |
| `customer_group` | link Customer Group | no | |
| `territory` | link Territory | no | |
| `tier` | text | no | Tier name |
| `min_lifetime_spend` | currency | no | |
| `enrolled_from` | date | no | |
| `enrolled_to` | date | no | |
| `min_orders` | int | no | |
| `max_orders` | int | no | |
| `last_order_within_days` | int | no | |
| `members` | table | for Static Members | Rows: `{ "customer": "<Customer name>" }`. `customer_name` is display-only |

## Event types

| Action | Call |
| --- | --- |
| List | `GET api.loyalty.event_types?page=1&page_size=50` |
| Open | `GET api.loyalty.event_type?name=` |
| Create | `POST api.loyalty.event_type.create` |
| Save | `POST api.loyalty.event_type.update` with `name` |

Built-in codes already exist: `customer_signup`, `first_order`, `birthday`, `feedback_submitted`, `referral`. When `is_builtin` is `1`, the code cannot be changed and there is no delete. The user may still change `enabled`, `description`, `once_per_customer`, and `cooldown_days`.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `event_code` | text | yes on create | snake_case. This becomes the document name |
| `enabled` | check | no | Default `1` |
| `description` | text | no | |
| `once_per_customer` | check | no | |
| `cooldown_days` | int | no | `0` = no cooldown |
| `is_builtin` | check | read only | Never send it |

External systems award these with `POST api.loyalty.events.emit`. That route is not part of this screen.

## Tier changes

`GET api.loyalty.tier_changes?account=<member number>&page=1&page_size=20`

Columns: `changed_at`, `from_tier`, `to_tier`, `reason`, `customer`. Read only. Put this table on the account page. No create or edit.

## What not to build

- Creating, editing, or deleting a loyalty transaction.
- Deleting a programme, campaign, reward, account, or segment.
- Password fields and regenerating the member-token secret.
- A second loyalty calculation on the client. Display `point_value`, balances, and `tier_progress` from the response.
- The customer routes `api.loyalty.campaigns` and `api.loyalty.rewards` on these admin screens. Use `campaigns.list` and `rewards.list`.

## Minimum create examples

Programme:

```json
{
  "programme_name": "Spring Rewards",
  "company": "Spring Sushi",
  "start_date": "2026-11-04",
  "point_value": 0.01,
  "status": "Draft",
  "base_rules": [
    {
      "rule_name": "Standard earn",
      "rule_type": "Spend Rate",
      "points": 1,
      "per_amount": 1
    }
  ],
  "tiers": [
    { "tier_name": "Star 1", "rank": 1, "threshold": 0, "earn_multiplier": 1 }
  ]
}
```

Then `POST api.loyalty.programme.set_status` with `{ "name": "<returned name>", "status": "Active" }`.

Settings, after that programme is Active:

```json
{
  "active_programme": "<programme name>",
  "liability_account": "<liability account>",
  "expense_account": "<expense account>",
  "enabled": 1
}
```
