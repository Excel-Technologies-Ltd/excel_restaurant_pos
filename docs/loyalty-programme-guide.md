# ArcPOS Loyalty Programme — Complete Guide

**Audience:** restaurant owners, managers, finance, support staff, and the developers of
the storefront (web and mobile app), the POS, and any system that talks to the loyalty
backend.

**Related documents**

| Document | Use it for |
| --- | --- |
| `docs/loyalty-api.md` | The exact API contract (every route, parameter and response field) |
| `docs/loyalty-frontend-guide.md` | A short screen-by-screen checklist for the storefront and the POS |
| `docs/loyalty-programme-implementation-plan.md` | The original design and the reasons behind it |

**How to read this guide.** Every rule in this document is one of three kinds, and each is marked:

| Marker | Meaning |
| --- | --- |
| **[Policy]** | A business choice an administrator sets in the system. It can change without a developer. |
| **[System]** | Behaviour the software always enforces. It cannot be switched off; changing it is a code change. |
| **[Recommendation]** | Good practice we advise, but neither the software nor this guide forces it. |
| **⚠ Decision to confirm** | A business question nobody has answered yet. The system has a default, but the business must confirm it (or pick another value) before go-live. Section 15 collects them all. |

---

## Contents

1. [Overview and core concepts](#1-overview-and-core-concepts)
2. [Initial administrator setup](#2-initial-administrator-setup)
3. [Flexible programme rules and campaigns](#3-flexible-programme-rules-and-campaigns)
4. [The customer journey](#4-the-customer-journey)
5. [Redemption and expiration](#5-redemption-and-expiration)
6. [Apple Wallet and Google Wallet](#6-apple-wallet-and-google-wallet)
7. [Web, mobile and desktop application integration](#7-web-mobile-and-desktop-application-integration)
8. [Administrator dashboard and management](#8-administrator-dashboard-and-management)
9. [Business rules and edge cases](#9-business-rules-and-edge-cases)
10. [Security, permissions and audit](#10-security-permissions-and-audit)
11. [Reporting and analytics](#11-reporting-and-analytics)
12. [Technical architecture and data model](#12-technical-architecture-and-data-model)
13. [End-to-end workflows with examples](#13-end-to-end-workflows-with-examples)
14. [Testing and go-live checklist](#14-testing-and-go-live-checklist)
15. [Decisions to confirm](#15-decisions-to-confirm)
16. [Known gaps and future enhancements](#16-known-gaps-and-future-enhancements)
17. [Glossary](#17-glossary)

---

## 1. Overview and core concepts

### 1.1 What the loyalty programme is

The ArcPOS loyalty programme rewards customers for ordering. Every eligible order earns
**points**. Points can then be spent as money on a later order, or exchanged for a
**reward** such as a $5-off voucher or a free dessert. Members also climb **tiers**
(for example Bronze → Silver → Gold) that earn points faster.

It works everywhere the restaurant sells directly:

- dine-in and takeout at the table (POS)
- in-store pickup (POS)
- online delivery and online pickup (website and mobile app)

Third-party marketplaces (Uber Eats, DoorDash) **[System]** neither earn nor redeem points.
Those customers belong to the marketplace, the restaurant is paid a different price, and
the walk-in customer the order is booked to is not a real person.

### 1.2 Why the business needs it

| Benefit | How the programme delivers it |
| --- | --- |
| More repeat visits | Members have a balance waiting for them and a tier to keep. |
| Higher order value | Spend thresholds ("spend $40, get 100 bonus points") and tier multipliers reward bigger baskets. |
| Fill quiet periods | Time-limited campaigns ("double points Monday 2–5 pm") steer demand. |
| Push specific items | Item and category rules ("50 bonus points on any new pizza") promote margins or new menu items. |
| Know your customers | Every member has a ledger of orders, rewards and visits, which feeds segments and campaigns. |
| Direct relationship | Points and passes in Apple/Google Wallet keep the brand on the customer's phone, outside the marketplace apps. |
| Controlled cost | The value of every unspent point is tracked as a liability in the accounts, with expiry, caps and budgets to keep the cost predictable. |

### 1.3 Benefits for customers

- One balance across the restaurant, the website, the app and the wallet pass.
- Points are worth real money at checkout, with no voucher codes to hunt for.
- Clear history: every point earned, spent, returned or expired is listed with its reason.
- Warnings before points expire.
- A digital card in Apple Wallet or Google Wallet that updates itself.

### 1.4 Core concepts

| Term | Plain meaning |
| --- | --- |
| **Programme** | The rulebook: what a point is worth, how points are earned, how they can be spent, when they expire and which tiers exist. One programme is "active" at a time. |
| **Member / Loyalty Account** | A customer who has joined. Each customer has at most one account. It has a **member number** (e.g. `LM-8F3K2Q9X`). |
| **Point value** | What one point is worth when spent. Default `0.01`, so 100 points = $1.00. |
| **Ledger** | The permanent list of every points movement for every member. Balances are calculated from it; nothing in it is ever edited or deleted. |
| **Lot** | One batch of credited points (for example "42 points from order SINV-0012, expiring 2027-10-19"). Spending uses the oldest-expiring lots first. |
| **Pending points** | Points earned but not yet spendable, while the return window is open. |
| **Available points** | Points the member can spend right now. |
| **Rule** | A single earning instruction, e.g. "1 point per $1 spent" or "50 points per pizza". |
| **Campaign** | A set of rules that apply only in a time window and/or to certain members, e.g. "Summer double points". |
| **Event** | Something other than a purchase that earns points: sign-up, first order, birthday, feedback, referral, or any custom event. |
| **Tier** | A membership level, reached by spending, that can multiply earning and show benefits. |
| **Reward** | A catalogue item bought with points: an order discount voucher or a free item. |
| **Redemption** | Spending points, either as payment on an order or for a reward. |
| **Member token** | The code in the member's QR code and wallet pass. It identifies the member. On its own it never allows anyone to spend points. |
| **Liability** | The money value of all unspent points. The restaurant owes this to its members, so it sits in the accounts. |

### 1.5 The lifecycle at a glance

```
 Admin sets up programme ─► Customer joins ─► Orders and events earn points
                                                    │
                                                    ▼
                     Pending (return window) ─► Available ─► Spent on an order or reward
                                                    │
                                                    ├─► Returned (refund / cancel)
                                                    └─► Expired (unused too long)
```

---

## 2. Initial administrator setup

All setup happens in the ERPNext desk, in the **Loyalty** workspace. The person doing
it needs the **ArcPOS Loyalty Manager** or **System Manager** role.

### 2.1 Step 0 — before you start (one-time, technical)

| Step | Who | What |
| --- | --- | --- |
| Install / update the app and run `bench migrate` | Developer / DevOps | Creates the loyalty records, the **Loyalty Points** mode of payment, the built-in event types, and hides ERPNext's own loyalty fields (they are not used). |
| Install Python dependencies | DevOps | `bench setup requirements` (or rebuild the image). Needed for wallets: `google-auth`, `httpx[http2]`. |
| Make sure the scheduler is running | DevOps | `bench enable-scheduler`. Expiry, tiers, birthdays, wallet retries and the accounting true-up all depend on it. |

### 2.2 Step 1 — accounts (Finance)

Create two accounts in the chart of accounts for the company:

| Account | Type | Purpose |
| --- | --- | --- |
| *Loyalty Points Liability* | Current liability | What unspent points are worth. |
| *Loyalty Programme Expense* | Expense (e.g. under Marketing) | The cost of points given out. |

A cost center for loyalty is optional; you can use the main one.

> ⚠ **Decision to confirm (Finance):** where the liability and expense accounts sit in
> the chart of accounts, and whether the liability is trued up **daily** (default),
> **monthly**, or **off**.

### 2.3 Step 2 — create the programme

Desk → Loyalty → **Loyalty Programme** → New.

#### General

| Field | Default | What it controls |
| --- | --- | --- |
| Programme Name | — | Shown to customers unless a display name is set in Settings. |
| Company | — | The company whose orders and accounts are used. |
| Status | Draft | **Draft**: nothing happens. **Active**: earning and redemption run. **Paused**: no earning or redemption, but balances are kept and still expire. **Ended**: closed. |
| Start / End Date | Today / empty | The programme is only live between these dates. |
| Currency | company currency | Currency of point value. |
| **Point Value** | 0.01 | What one point is worth when spent. **[Policy]** ⚠ *Decision to confirm.* |
| Points Rounding | Floor | How fractional points are rounded (Floor / Round / Ceil). Floor means 42.9 → 42. |
| Terms | — | Terms and conditions, shown in the app and on wallet passes. |

#### Earning

| Field | Default | What it controls |
| --- | --- | --- |
| **Earn Basis** | Net Total (excl. tax) | Earn on the amount before tax, or on the grand total. **[Policy]** |
| **Earn On** | Paid | When points are awarded: when the order is fully paid, or as soon as it is submitted. **[Policy]** "Paid" is recommended: a submitted-but-unpaid order has not earned anything yet. |
| **Pending Days** | 0 | The return window. Earned points wait this many days before they can be spent. 0 = spendable at once. **[Policy]** ⚠ *Decision to confirm.* |
| Exclude Gift Card Items | On | Buying a gift card does not earn points (the points come when the gift card is spent on food). **[Recommendation]** keep on. |
| Earn on Loyalty-Paid Amount | Off | Off: the part of an order paid with points does not earn new points. **[Recommendation]** keep off. |
| Exclude Item Groups | — | Categories that never earn (e.g. alcohol, tobacco, deposits, tips). |
| Earn per channel | all on | Which channels earn: dine-in, in-store pickup, online delivery, online pickup. |
| Base Rules / Base Rule Items | — | The always-on earning rules (section 3). Typical: **Spend Rate, 1 point per 1.00**. |

#### Redemption

| Field | Default | What it controls |
| --- | --- | --- |
| Min Redeem Points | 0 | The smallest number of points that can be used on one order. |
| Max Redeem Points per Order | 0 (no limit) | A hard cap per order. |
| Max Redeem % of Order | 100 | The share of an order points may pay. 50 means points pay at most half. |
| Redeem Increment | 1 | Points must be used in multiples of this (e.g. 100 → 100, 200, 300…). |
| Redeem per channel | all on | Which channels may redeem. |
| Allow Negative Balance on Reversal | Off | What happens when a refunded order's points were already spent. Off: only what is left is taken back. On: the balance goes negative and future earning pays it off. **[Policy]** ⚠ *Decision to confirm.* |
| Restore Grace Days | 7 | When refunded points are given back after their original expiry date has passed, they get this many extra days. |

#### Expiry

| Field | Default | What it controls |
| --- | --- | --- |
| **Expiry Mode** | Fixed Days per Lot | **Fixed Days per Lot**: each batch of points expires N days after it was earned. **Rolling Inactivity**: nothing expires while the member keeps ordering; after N days with no activity the whole balance expires. **Never**: points never expire. **[Policy]** ⚠ *Decision to confirm.* |
| Expiry Days | 365 | The N above. |
| Expiry Notice Days | 30,7,1 | Members are warned this many days before points expire. |

> ⚠ **Check local law before choosing an expiry policy.** Some jurisdictions restrict
> the expiry of prepaid value or require notice. Points that are given away free are
> usually treated differently from purchased value, but confirm with your advisor.

#### Tiers

| Field | Default | What it controls |
| --- | --- | --- |
| Tier Basis | Lifetime Spend | What qualifies a member for a tier: lifetime spend, spend in the last 12 months, or points earned in the last 12 months. |
| Tier Review | Upgrade Immediately, Downgrade at Review | Members move up as soon as they qualify. They only move down at their review date (one year after reaching the tier). **Continuous** moves both ways every day. |
| Tiers table | — | One row per tier: name, rank (1 = lowest), threshold, earn multiplier, benefits text, pass colour. |

Example tiers:

| Tier | Rank | Threshold (lifetime spend) | Earn multiplier | Benefits |
| --- | --- | --- | --- | --- |
| Bronze | 1 | 0 | 1.0 | Earn 1 point per $1 |
| Silver | 2 | 500 | 1.25 | 25% more points |
| Gold | 3 | 1,500 | 1.5 | 50% more points, birthday dessert |

Set the programme's **Status** to **Active** when it is ready.

### 2.4 Step 3 — Loyalty Settings

Desk → Loyalty → **Loyalty Settings** (one page for the whole site).

| Tab | Field | Default | Notes |
| --- | --- | --- | --- |
| General | **Enabled** | Off | The master switch. Off = every loyalty feature is silent everywhere. You can only turn it on once an Active Programme is chosen. |
| General | Active Programme | — | The programme new activity posts to. |
| General | Auto Enrol on Sign-up | On | Customers who create a website/app account join automatically. **[Policy]** |
| General | Auto Enrol on First Order | On | Customers who order without having joined are enrolled on their first eligible order. **[Policy]** |
| General | Excluded Customers | — | Customers who never join or earn. The walk-in/default customers from ArcPOS Settings are **[System]** always excluded. |
| General | Adjustment Approval Threshold | 500 | Manual adjustments bigger than this (up or down) need a Loyalty Manager's approval. **[Policy]** |
| General | POS Step-up Threshold (Points) | 0 (off) | Staff redemptions above this need a one-time code sent to the member. **[Policy]** ⚠ *Decision to confirm.* |
| General | Refund Points for Expired Reward Vouchers | On | A reward voucher that expires unused gives its points back. **[Policy]** |
| General | Email / Push Notifications | On / On | Default preferences for new members. |
| General | Member Token Secret | auto | Generated automatically. **Never change it casually**: every QR code and pass barcode stops working. |
| Accounting | Loyalty Mode of Payment | *Loyalty Points* | The payment method used when points pay for an order. Saving links it to the liability account. |
| Accounting | Liability Account, Expense Account, Cost Center | — | From Step 1. Must belong to the programme's company. |
| Accounting | Liability True-up | Daily | Daily, Monthly or Off. See section 11.3. |
| Accounting | Reward Voucher Pricing Rule | — | Needed by ERPNext for coupon codes. Falls back to the default pricing rule in ArcPOS Settings. |
| Notifications | Email templates | — | One per message: points earned, redeemed, expiring, tier change, reward voucher, verification code. A message with no template is not emailed. |
| Google Wallet | see section 6 | | |
| Apple Wallet | see section 6 | | |
| Branding | Display name, logo, icon, strip image, colours | — | Used on wallet passes. |

Then tick **Enabled** and save.

### 2.5 Step 4 — events, segments, campaigns and rewards

These are optional on day one, but most restaurants launch with at least:

- a **sign-up bonus** (event rule on `customer_signup`)
- a **birthday bonus** (event rule on `birthday`)
- two or three **rewards** in the catalogue

They are explained in section 3.

### 2.6 Eligibility summary

| Who / what | Earns? | Redeems? | Controlled by |
| --- | --- | --- | --- |
| Member with Active account | Yes | Yes | **[System]** |
| Member with Suspended or Closed account | No | No | **[System]** |
| Customer not enrolled | Only after auto-enrolment on the first order (if on) | No | **[Policy]** |
| Walk-in / default POS customers | No | No | **[System]** + Excluded Customers **[Policy]** |
| Uber Eats / DoorDash orders | No | No | **[System]** |
| Channels switched off on the programme | No | No | **[Policy]** |
| Gift card purchases | No (default) | — | **[Policy]** |
| Excluded item groups | No | Points can still pay for them | **[Policy]** |
| Programme Paused / Ended / before start | No | No | **[Policy]** (status and dates) |

---

## 3. Flexible programme rules and campaigns

### 3.1 How rules work

A **rule** is one line in a rules table. Rules live in two places:

- **Programme → Base Rules**: always on, for every eligible order.
- **Campaign → Rules**: only while the campaign is live and only for its eligible members.

Each rule has a **Trigger**:

- **Purchase**: it runs on orders.
- **Event**: it runs when a named event happens (sign-up, birthday, …).

It also has a **Rule Type**:

| Rule type | What it gives | Example |
| --- | --- | --- |
| **Spend Rate** | *Points* for every *Per Amount* spent | 1 point per $1.00 |
| **Spend Threshold** | *Points* once, when spend reaches *Per Amount* | 100 bonus points when the order is $40 or more |
| **Item Quantity** | *Points* per unit of matching items | 20 points per pizza |
| **Item Spend** | *Points* per *Per Amount* spent on matching items | 2 points per $1 on desserts |
| **Fixed Bonus** | *Points* once, when the rule's conditions hold | 50 points on any order on a Tuesday |
| **Multiplier** | Multiplies points by *Multiplier* | ×2 (double points) |

#### Optional limits on every rule

| Field | Meaning |
| --- | --- |
| Applies To | **All Items**, or **Filtered**: only lines matching this rule's *Rule Item* rows (by Item, Item Group or Brand; an item group includes its sub-groups). |
| Min Order Amount / Min Qty | The rule only fires above these. |
| Order Number | e.g. 1 = only the customer's first order. 0 = any order. |
| Max Points per Order | A cap for this rule. 0 = none. |
| Priority | Higher runs first. |
| Exclusive | When this rule awards points, lower-priority rules in the same table are skipped. |
| Condition | An optional formula for anything the fields cannot express (below). |
| Multiplier Scope | For multipliers: multiply **base points** only, or **everything awarded so far**. |

#### Custom conditions

A condition is a short Python expression. It can only read the values below, and it
cannot touch the database. The system tests it on a sample order when you save, so a
typo is rejected at once. If a condition fails at award time, only that rule is
skipped; the rest of the order still earns.

| Value | Meaning |
| --- | --- |
| `order.total`, `order.eligible_amount` | Order total and the part that can earn |
| `order.channel` | `dine_in`, `in_store_pickup`, `online_delivery`, `online_pickup` |
| `order.weekday`, `order.hour` | e.g. `'Fri'`, `18` |
| `order.number` | This order's position among the customer's orders (1 = first) |
| `order.territory` | Customer territory |
| `order.items` | List of lines, each with `item_code`, `item_group`, `brand`, `qty`, `amount` |
| `customer.tier`, `customer.order_count`, `customer.days_since_last_order`, `customer.segments` | About the member |
| `event.code`, `event.payload` | For event rules |

Examples:

```python
order.weekday in ('Mon', 'Tue') and order.hour < 17          # weekday afternoons
customer.days_since_last_order is not None and customer.days_since_last_order > 60   # win-back
'Students' in customer.segments
sum(i.qty for i in order.items if i.item_group == 'Pizza') >= 2
event.payload.get('rating', 0) >= 4                          # feedback rule
```

#### The order in which points are calculated **[System]**

1. **Additive rules** (Spend Rate, Spend Threshold, Item Quantity, Item Spend, Fixed
   Bonus) run in each table (the programme's base rules, then each campaign's rules),
   highest priority first. An exclusive rule that fires stops lower-priority rules in
   its own table.
2. The member's **tier multiplier** is applied to **base** points (not to campaign
   bonuses).
3. **Multiplier rules** are applied, either to base points or to everything awarded so far.
4. Each award is **rounded** per the programme's rounding setting.
5. Each campaign award is **capped** by the campaign's points budget and per-customer cap.

Every award is recorded separately in the ledger, with the rule and campaign that
produced it, so a member sees "42 points — order" and "100 points — Summer bonus" as two
lines.

### 3.2 Points for total spend

**Base rule:** Spend Rate, Points 1, Per Amount 1.00, Applies To All Items.

*Example:* An order of $42.80 before tax with Floor rounding earns **42 points**. A Silver
member (×1.25) earns 42 × 1.25 = 52.5, rounded down to **52 points**, recorded as 42
plus a 10-point tier bonus line.

Add a **Spend Threshold** rule for basket building: "Spend $40, get 100 bonus points"
(Points 100, Per Amount 40.00).

### 3.3 Points for specific products or categories

1. Add a rule with Applies To **Filtered**, e.g. Item Quantity, 20 points.
2. In **Rule Items**, add rows that point at that rule (by its Rule ID or Name) with
   Applies To = Item / Item Group / Brand and the value, e.g. Item Group = *Pizza*.

*Example:* "20 points per pizza". An order with 2 Margherita and 1 Pepperoni earns
3 × 20 = 60 bonus points on top of the spend points.

Use **Item Spend** for "2 points per $1 on desserts", and **Exclude Item Groups** on
the programme for things that should never earn.

### 3.4 Seasonal and time-limited campaigns

Desk → Loyalty → **Loyalty Campaign** → New.

| Field | Meaning |
| --- | --- |
| Campaign Name, Title, Description, Image | Shown in the app when *Display in App* is on. |
| Status | Draft → Scheduled → Active → Ended (moves automatically every 10 minutes by date), or Paused by hand. |
| Start / End Datetime | The window. |
| Recurrence | **None**: one continuous window. **Weekly**: on Recurrence Days (e.g. `Fri,Sat`) between Recurrence Start and End Time; a window like 22:00–02:00 runs overnight correctly. **Yearly**: the same month/day window every year until *Recur Until*. |
| Eligible channels | Dine-in, in-store pickup, online delivery, online pickup. |
| Eligible Tiers / Segments / Territories | Empty = everyone. |
| Points Budget | Total points the campaign may give out. When it runs out, the campaign ends. 0 = unlimited. |
| Per Customer Cap | Max points one member can get from this campaign. 0 = unlimited. |
| Priority, Stackable | See "campaign conflicts" below. |
| Rules / Rule Items | The campaign's own rules (same types as above). |

The campaign page also offers:

- **Simulate on Order…**: pick an existing invoice and see what the campaign would award, without writing anything.
- **Duplicate**: copy a campaign (e.g. last year's summer promotion) as a new draft.
- Live counters: Points Issued, Participants and Orders.

**Campaign conflicts [System]:**
- **Stackable** campaigns (the default) all apply together.
- Of the **non-stackable** campaigns live for an order, only the one with the highest
  priority applies. The stackable campaigns still apply alongside it.
- Base programme rules always apply.

*Examples:*
- "**Double points weekends in December**": Weekly recurrence, days `Sat,Sun`, Start
  1 Dec, End 31 Dec, rule Multiplier ×2 on Base Points.
- "**Happy hour**": Weekly `Mon,Tue,Wed,Thu`, 15:00–17:00, Fixed Bonus 30 points.
- "**Summer launch, 10,000-point budget**": rule Item Quantity 50 points on Item Group
  *Summer Menu*, Points Budget 10,000, Per Customer Cap 200.

### 3.5 Custom events (sign-up, birthday, feedback, anything)

An **event type** names something that can happen to a customer. Built-in event types **[System]**:

| Event code | Fired when | Built-in frequency limit |
| --- | --- | --- |
| `customer_signup` | A storefront/app account is created and linked to a customer | Once per customer |
| `first_order` | The customer's first paid order | Once per customer |
| `birthday` | Daily at 09:00, for members whose Customer *Date of Birth* is today (Feb 29 birthdays are celebrated on Feb 28 in non-leap years) | Cooldown 300 days |
| `feedback_submitted` | A feedback form is completed | Set by you |
| `referral` | Sent by an integration (no built-in emitter yet) | Set by you |

You can create more (Desk → Loyalty → **Loyalty Event Type**), for example
`app_review_left`, `instagram_follow` or `survey_completed`. Each one has:

- **Once per Customer**: the event can only award a customer once.
- **Cooldown Days**: a gap that must pass between two awards to the same customer.

To give points for an event, add a rule with **Trigger = Event**, choose the event type,
and use Fixed Bonus (or Spend Rate on `payload.amount`). Put it in the programme's base
rules (always) or in a campaign (time-limited or targeted).

*Example — "5 points when a customer signs up":*
Programme → Base Rules → new row: Trigger *Event*, Event Type `customer_signup`, Rule
Type *Fixed Bonus*, Points **5**.

External systems trigger custom events through `api.loyalty.events.emit` (section 7.6).

### 3.6 Special promotions, bonus points and customer-specific offers

| Need | How to do it |
| --- | --- |
| A bonus for everyone this week | Campaign with a Fixed Bonus or Multiplier rule and a one-week window. |
| An offer only for VIPs | Campaign with Eligible Tiers = `Gold`. |
| An offer for a hand-picked list of customers | **Segment** with Match Mode *Static Members* and the customer list, then a campaign targeting that segment. |
| An offer for a behaviour group | **Segment** with filters: customer group, territory, tier, minimum lifetime spend, enrolment dates, order count range, "last order within N days". |
| Win back lapsed customers | Segment "last order within 365 days" plus a condition `customer.days_since_last_order > 60`, or a condition-only rule. |
| A one-off goodwill gift to one person | A **Loyalty Adjustment** (section 8.4), not a campaign. |
| First-order welcome bonus | Event rule on `first_order`, or a Purchase rule with Order Number = 1. |
| Rewards to spend points on | **Loyalty Reward** catalogue (section 5.3). |

Segments are recalculated on demand and cached for one hour.

---

## 4. The customer journey

### 4.1 Joining

| Path | What happens |
| --- | --- |
| Signs up on the website or app | Auto-enrolled (if *Auto Enrol on Sign-up* is on). The `customer_signup` event fires, e.g. +5 points. |
| Taps "Join" in the app | `api.loyalty.enrol`. Used when auto-enrolment is off, or for customers who existed before the programme launched. |
| First eligible order | Auto-enrolled (if *Auto Enrol on First Order* is on), and the order earns. |
| At the counter | The cashier taps **Enrol** on the order (`api.loyalty.staff_enrol`). |
| By an administrator | Created in the desk, or imported. |

Each customer can have **one** account **[System]**. Enrolling twice returns the same
account, even when sign-up and a first order race each other. The new member gets:

- a member number
- the lowest tier
- the default notification preferences

> ⚠ **Decision to confirm:** do customers need to accept the programme terms explicitly
> (a consent checkbox) before joining, or is joining automatic on sign-up? The system
> enrols automatically by default. If consent is needed, turn auto-enrolment off and
> show a "Join" button that records acceptance.

### 4.2 Earning

1. The customer places an order on any eligible channel.
2. When the order is **paid** (or submitted, depending on *Earn On*), the system works
   out the points and records them. The receipt shows *Points earned*
   (`custom_loyalty_points_earned`).
3. If *Pending Days* is above 0, the points show as **Pending** until the return
   window passes. They then become **Available** automatically (checked hourly).
4. The member is notified by email and/or push, if their preferences allow it.
5. Their wallet pass updates within about 30 seconds.

Before paying, the app can show "**You'll earn N points**" (`preview_earning`).

### 4.3 Checking balance and status

The app's loyalty screen (`api.loyalty.me`) shows:

- **Available points** and their money value
- **Pending points** ("available after the return window")
- **Expiring soon**: the next expiry date and how many points
- **Tier**, with a progress bar to the next tier
- **Lifetime totals**: points earned, redeemed and expired
- **QR code** (member token), to show at the counter
- **Add to Apple Wallet / Google Wallet** buttons

### 4.4 Redeeming

**At checkout (points as payment):**

1. The app asks how many points can be used (`redemption_options`) and shows a slider
   from the minimum to the maximum, in steps of the increment.
2. The member chooses, e.g. 500 points = $5.00.
3. The order now shows "**To pay: $X**". The card is charged only that amount.
4. When the order is paid, the points are spent.

**For a reward:**

1. The member opens the rewards catalogue and picks, e.g., "Free dessert — 300 points".
2. The points are spent at once and a single-use voucher code is issued.
3. The voucher is applied at checkout like any coupon.

**At the counter:**

1. The cashier scans the member's QR code (or searches by member number, phone or email).
2. The cashier applies points to the order.
3. For large redemptions, the member reads out a one-time code sent to their email
   (step-up verification, if turned on).

### 4.5 History

`api.loyalty.transactions` lists every movement, newest first, filterable by type and date:

| Type | Example line |
| --- | --- |
| Earn | +42 · Order SINV-26-00123 · expires 2027-10-19 |
| Bonus | +100 · Summer double points |
| Redeem | −500 · Order SINV-26-00150 |
| Redeem | −300 · Voucher RWD-… (Free dessert) |
| Reverse | −42 · Order SINV-26-00123 returned |
| Expire | −80 · Points expired |
| Adjust | +200 · Goodwill — late delivery |

### 4.6 Notifications

| Message | When | Channel |
| --- | --- | --- |
| Points earned | After an order earns | Email template + push |
| Points redeemed | After points are spent | Email + push |
| Points expiring | 30, 7 and 1 days before (configurable) | Email + push |
| Tier change | On upgrade or downgrade | Email + push |
| Reward voucher | When a reward is bought | Email + push |
| Verification code | When a cashier requests step-up | Email, sent immediately |

**[System]** behaviour:
- Each notification is sent at most once.
- It is only sent after the change is saved, so a failed order never notifies anyone.
- It respects the member's own preferences (`api.loyalty.preferences`).
- Push goes through Expo to the mobile app.

### 4.7 Leaving and account status

An administrator can set an account to:

- **Suspended**: no earning or redemption, and the balance is kept, e.g. while
  investigating fraud.
- **Closed**: the wallet passes are voided.

> ⚠ **Decision to confirm:**
> - What happens to the balance when a member asks to leave or delete their data
>   (forfeit, or convert)?
> - How long are closed accounts kept?

---

## 5. Redemption and expiration

### 5.1 Points as payment **[System]** unless marked

- Points are a **payment method** (Mode of Payment *Loyalty Points*), not a discount.
  Tax is charged on the full order, and points pay part of the bill like cash would.
- **Conversion:** value = points × point value. With 0.01, 500 points pay $5.00. **[Policy]**
- **Limits** (all **[Policy]**), applied together. The lowest one wins:
  - Minimum points per order (`min_redeem_points`)
  - Multiples of the increment (`redeem_increment`)
  - Maximum points per order (`max_redeem_points_per_order`)
  - Maximum % of the order (`max_redeem_percent_of_order`)
  - Never more than the amount still due **[System]**
  - Never more than the available balance, minus points held by other orders in card checkout **[System]**
- **Partial redemption:** members can use any allowed amount, not all-or-nothing.
- **Coupons and gift cards** can be used on the same order. Points are capped against
  what is left after those discounts.
- **Draft orders** (online cart): applying points only **reserves** them. They are
  spent when the order is submitted.
- **Dine-in orders already sent to the kitchen:** applying points spends them at once
  and lowers the outstanding amount.
- If the order changes after points were applied, the points are re-checked, and
  silently reduced if the order shrank.
- **Card checkout hold:** once the member starts card payment, their applied points (and
  gift card amounts) are **held** for that order. Another device cannot spend them
  meanwhile. If they were spent elsewhere first, checkout stops *before* the card is
  charged, with "Only N loyalty points are available now…". A card that has been
  charged **always** completes the order (section 9.2).

### 5.2 Step-up verification (POS)

If *POS Step-up Threshold* is above 0, a cashier who redeems more points than that must:

1. Request a code for the exact number of points (`request_otp`). The member receives
   the 6-digit code with the amount stated.
2. Enter the code the member reads out (`verify_otp`).

**[System]** rules:
- The code is valid for 5 minutes and covers exactly that amount.
- Wrong attempts and the number of sends are limited.
- The proof lives on the server. The POS cannot mark its own order as verified.

### 5.3 Rewards catalogue

Desk → Loyalty → **Loyalty Reward**.

| Field | Meaning |
| --- | --- |
| Reward Type | **Order Discount Voucher** (flat amount or percentage, with an optional cap) or **Free Item** (a voucher worth the item's selling price, only valid on orders that contain that item). |
| Points Cost | What it costs. |
| Voucher Validity Days | How long the voucher lasts (default 30). |
| Redemption Allowed On | All, POS, Dine-in, In Store Pickup, Online Pickup, Online Delivery, Only Online. |
| Min Order Amount | Minimum order to use the voucher. |
| Eligible Tiers | e.g. Gold-only rewards. |
| Stock Limit / Per Customer Limit | 0 = unlimited. |
| Active From / To | Availability window. |

**[System]** rules:
- Buying a reward is **idempotent**: a double tap or a retried request returns the same
  voucher and spends the points once.
- If the voucher expires unused and *Refund Points for Expired Reward Vouchers* is on,
  the points are given back.

### 5.4 Expiration

| Mode | How it works | Example (365 days) |
| --- | --- | --- |
| **Fixed Days per Lot** | Each batch of points expires 365 days after it was earned. Spending uses the earliest-expiring points first, so members lose as little as possible. | Points earned 1 Mar 2026 expire 1 Mar 2027, even if the member orders weekly. |
| **Rolling Inactivity** | While the member keeps having activity, nothing expires. After 365 days with no activity, the whole balance expires. | A member who orders every few months never loses points. |
| **Never** | Points never expire. | — |

**[System]** behaviour:
- Expiry runs daily at **00:30**.
- Warnings go out at 09:00 on the configured notice days. Each warning is sent only once.
- Expired points leave the liability at the next true-up.
- Points from a paused or ended programme still expire on schedule.

### 5.5 Refunds and cancellations **[System]**

| Situation | What happens to points earned | What happens to points spent |
| --- | --- | --- |
| Order **cancelled** | All points the order earned are taken back. | All points used on it are given back. |
| **Partial refund** (credit note / return) | Taken back **pro rata**. Item rules only count the returned lines that matched them (returning the 2 pizzas takes back the pizza bonus; returning a drink does not). | Given back pro rata. |
| Earned points already spent | **Allow Negative Balance off** (default): only what is left is taken back, and the rest is written off. **On**: the balance goes negative, and future earning pays it back first. **[Policy]** | — |
| Restored points whose original expiry has passed | — | Given back with *Restore Grace Days* (default 7) to use them. |
| Reward voucher not used and expired | — | Points refunded if the setting is on. **[Policy]** |

Given-back points keep their **original expiry date**, so a refund can never be used to
extend points.

### 5.6 Manual adjustments

Staff can add or remove points with a reason (Goodwill, Correction, Promotion,
Migration, Other) and remarks. Credits can have their own expiry date. See section 8.4
for the approval workflow.

---

## 6. Apple Wallet and Google Wallet

### 6.1 What the pass is

The member's loyalty card can be saved to Apple Wallet (iPhone) or Google Wallet
(Android). The pass shows:

- the programme name and logo
- member name and number
- **points balance** and its money value
- tier, pending points, the next expiry and tier benefits
- terms
- a **QR code** (the member token), which the cashier scans

The pass **holds no data of its own [System]**. Everything on it is rendered from the
backend, and the backend pushes updates when something changes. The pass's colour
follows the member's tier (if the tier has a pass colour), or the default colour from
Settings → Branding.

### 6.2 Issuing a pass

**Google Wallet**
1. The app calls `GET api.loyalty.wallet.google_save_url` and receives a signed link.
2. The member taps "Add to Google Wallet" and saves the pass.
3. Google tells the backend the pass was saved (`google_callback`), and the pass shows
   as **Installed** in the app.

**Apple Wallet**
1. **Browser:** the app calls `GET api.loyalty.wallet.apple_pass_link`, which returns a
   signed link valid for 5 minutes. The app navigates to it, and Safari offers "Add to
   Apple Wallet".
2. **Native app:** call `GET api.loyalty.wallet.apple_pass` with the user's
   `Authorization` header, and hand the `.pkpass` file to PassKit.
3. Once added, the iPhone registers itself with the backend's PassKit web service
   (`/loyalty-wallet/apple/v1/...`). The pass shows as **Installed**.

Only Active members can get a pass **[System]**.

### 6.3 How updates reach the pass **[System]**

1. Something changes: points earned or spent, expiry, tier, status, or a reissued token.
2. The backend queues a sync for that member. Several changes within 30 seconds are
   combined into one update, and the last change is never lost.
3. **Google:** the backend updates the pass object through Google's Wallet API, and
   Google updates the phone.
4. **Apple:** the backend sends an empty push notification to each registered device.
   The iPhone then asks the backend for the latest pass and downloads it.
5. Updates that fail are retried every 5 minutes with back-off.
6. Every night at 03:00, every pass is checked against the backend, and any that
   drifted are fixed.
7. A **reissued token** (lost phone) and a **closed account** update or void the passes.

### 6.4 Using the pass

- At the counter: the cashier scans the QR code from the wallet pass or from the app.
  Both carry the same member token.
- Scanning only **identifies** the member. Spending still happens on the order in the
  POS, and step-up verification still applies above the threshold.
- The pass has no payment ability of its own; it is a membership card.

### 6.5 Configuration (Settings → Google Wallet / Apple Wallet / Branding)

**Google Wallet**

| Item | Where to get it |
| --- | --- |
| Issuer ID | Google Pay & Wallet Console. Google must approve the issuer for public use. |
| Service Account Key (JSON) | A Google Cloud service account with the Wallet API enabled, added as a user in the Wallet Console. Attach it with **Private** ticked. |
| Save Button Origins | The storefront addresses, one per line, e.g. `https://order.example.com`. |
| Class Suffix | Optional; defaults to the programme name. |
| Callback Secret | Automatic. |

**Apple Wallet**

| Item | Where to get it |
| --- | --- |
| Pass Type ID, Team ID | Apple Developer account (paid). |
| Pass Type certificate (`.p12`) + password | Created for that Pass Type ID. Attach it as **Private**. |
| Apple WWDR certificate (G4) | Downloaded from Apple. Attach it as **Private**. |
| Organization Name | Your business name. |
| Web Service URL | `https://<api-domain>/loyalty-wallet/apple`. It must be public HTTPS, and the proxy must let GET, POST and DELETE through. |
| APNs Environment | Production (Sandbox only for development passes). |

**Branding**

| Item | Notes |
| --- | --- |
| Pass Icon (PNG) | **Required for Apple** |
| Logo, strip image | Optional |
| Background, foreground and label colours | Optional |
| Display name | Optional |

**[System]** credentials attached as public files are refused on save, so a private key
can never be downloaded from `/files/`.

> ⚠ **Decisions to confirm:**
> - Launch with both wallets, one, or neither?
> - Who owns the Apple Developer and Google issuer accounts? Certificates expire
>   yearly; who renews them?

---

## 7. Web, mobile and desktop application integration

### 7.1 Who does what

| Responsibility | Loyalty backend | Client apps (web, mobile, POS) |
| --- | --- | --- |
| Balances, tiers, expiry | Calculates them and is the only source of truth | Display what the API returns. Never calculate. |
| Earning | Awards points when orders are paid | Optionally show a preview |
| Redemption limits | Enforces them | Show the allowed range from `redemption_options` |
| Amount to charge | Computes `amount_due` | Charge `amount_due`, never `grand_total` |
| Idempotency | De-duplicates | Send an `Idempotency-Key` for rewards; reuse it on retry |
| Identity | Resolves the member from the session | Send the user's token; never send a customer id for customer endpoints |
| Errors | Returns human-readable messages | Show them as-is |
| Wallet passes | Builds, signs and updates them | Show the add buttons and open the links |
| Notifications | Sends email and push | Register the Expo push token (existing app flow) |

### 7.2 Applications

| Application | Who uses it | Integration |
| --- | --- | --- |
| **order-web** (website) | Customers | Customer endpoints |
| **Mobile app** (customer) | Customers | Same customer endpoints, plus Expo push and native PassKit |
| **pos-web** (POS, also runs in the desktop shell at the counter) | Cashiers, waiters, managers | Staff endpoints |
| **ERPNext desk** | Administrators, finance | Doctypes, reports, workspace |
| **External systems** (CRM, survey tool, referral partner) | Integrations | Event API with an API key |

> ⚠ **Decision to confirm:** is there a separate desktop application besides pos-web in
> a desktop shell? If so, it uses the same staff endpoints and authentication as pos-web.

### 7.3 Authentication and identification

- All endpoints are `/api/method/<route>`. Responses have the shape
  `{"message": {"success": true, "message": "...", "data": {...}}}`.
- **Customer apps** authenticate as the logged-in user (the storefront's existing JWT
  bearer token). The backend works out the member from the session, so a customer can
  only ever see and spend their own points.
- **Staff apps** authenticate as a staff user with a staff role (section 10.1).
- **Integrations** use an API key/secret of a user with *ArcPOS Loyalty Manager*.
- **Member identification at the counter:** scan the member token (QR), or search by
  member number, phone or email. Results show **masked** email and phone.

### 7.4 Customer endpoints (web and mobile)

| Purpose | Endpoint |
| --- | --- |
| Status / balance / tier / QR / wallet state | `GET api.loyalty.me` |
| Join | `POST api.loyalty.enrol` |
| History | `GET api.loyalty.transactions` (filters: `type`, `from_date`, `to_date`, `page`, `page_size` ≤ 100) |
| Live campaigns | `GET api.loyalty.campaigns` |
| Rewards catalogue | `GET api.loyalty.rewards` |
| Buy a reward | `POST api.loyalty.redeem_reward` + `Idempotency-Key` header |
| "You'll earn N points" | `POST api.loyalty.preview_earning` |
| Redemption range for an order | `GET api.loyalty.redemption_options?sales_invoice=…` |
| Apply / remove points | `POST api.loyalty.apply_points`, `POST api.loyalty.remove_points` |
| Notification preferences | `GET/POST api.loyalty.preferences` |
| Wallets | `google_save_url`, `apple_pass_link`, `apple_pass` |

**Checkout sequence (web and app):**

```
cart (draft order) ─► preview_earning ─► redemption_options ─► apply_points
      ─► api.payments.get_ticket   (charges amount_due; holds points + gift cards)
            ├─ payment_required: false  → points/gift card covered everything → confirmation
            ├─ "Only N loyalty points are available now…" → re-read options, let member re-choose
            └─ ticket → Moneris card payment → receipt_payment → order submitted → points spent, new points earned
```

### 7.5 Staff endpoints (POS / desktop)

| Purpose | Endpoint |
| --- | --- |
| Find member (scan or search) | `GET api.loyalty.lookup?query=…` |
| Enrol at the counter | `POST api.loyalty.staff_enrol` |
| Points on the order | `redemption_options`, `apply_points`, `remove_points` |
| Step-up code | `POST api.loyalty.request_otp`, `POST api.loyalty.verify_otp` |
| Manual adjustment | `POST api.loyalty.adjust` |
| Lost phone / shared QR | `POST api.loyalty.reissue_pass` (managers) |

**POS payment rule [System]:** cash/card rows must add up to `grand_total − loyalty
value`. The POS never adds a loyalty payment row itself; the backend books it.

**Receipts:** print points redeemed, their value, and points earned.

### 7.6 Integration endpoint (external systems)

```
POST /api/method/api.loyalty.events.emit
Authorization: token <api_key>:<api_secret>

event_code=survey_completed
customer=CUST-00042
reference=survey-9f2c1         ← required, unique per occurrence (de-duplication key)
payload={"amount": 0, "rating": 5}
```

The response is `{entries, points}`. Sending the same `reference` again does **not**
award twice **[System]**.

### 7.7 Error handling

| Response | Meaning | Client action |
| --- | --- | --- |
| 401 | Session expired | Refresh the token and retry |
| 403 | Not your order / not allowed | Show the message; do not retry |
| 429 | Rate limited | Wait and retry later |
| `ValidationError` | A business rule refused the action (e.g. "At most 1,500 points can be used on this order") | Show the message as-is; it is written for the user |
| Loyalty disabled | `me` reports not available | Hide loyalty UI |

**Safe to retry [System]:**
- `redeem_reward` with the same key
- `apply_points` with the same points
- `emit` with the same reference

**[System]** A loyalty failure never blocks an order or payment it rides on. Earning
runs as a side effect, and an hourly backstop awards anything that was missed.

---

## 8. Administrator dashboard and management

### 8.1 The Loyalty workspace

Desk → **Loyalty**.

**Number cards:**
- Active Members
- Outstanding Points
- Outstanding Liability
- Points Earned / Redeemed / Expired This Month
- Active Campaigns

**Links:**

| Group | Screens |
| --- | --- |
| Setup | Loyalty Settings, Loyalty Programme, Loyalty Event Type, Loyalty Segment |
| Members | Loyalty Account, Loyalty Transaction, Loyalty Adjustment, Loyalty Tier Change |
| Campaigns & Rewards | Loyalty Campaign, Loyalty Reward |
| Wallets & Logs | Wallet Pass, Wallet Device Registration, Loyalty Notification Log, Loyalty Liability Run |
| Reports | see section 11 |

### 8.2 Managing campaigns and rules

- Create the campaign in **Draft**, add rules, and use **Simulate on Order…** against
  a recent real order.
- Set dates and change the status to **Scheduled**. The system activates and ends it
  on time, and also ends it when the budget runs out.
- **Pause** stops it immediately. **Duplicate** reuses it next season.
- Watch its counters and the *Loyalty Campaign Performance* report.

**[Recommendation]**
- Never edit the rules of a live campaign to change past behaviour; it does not change
  points already awarded.
- End the campaign and create a new one, so reports stay meaningful.

### 8.3 Investigating a member

On a **Loyalty Account**:

- See balances, tier, status, lifetime totals, enrolment source and preferences.
- **Ledger**: every transaction for the member, with links to the source order, campaign, reward or adjustment.
- **Adjust Points**: start an adjustment.
- **Recompute Balance**: rebuild the cached figures from the ledger (safe to run any time).
- **Reissue Pass**: invalidate the old QR code (lost phone, shared screenshot).
- Change status to Suspended or Closed.

**Typical question: "Why did I only get 40 points?"**
1. Open the order's ledger lines. Each award shows its rule and campaign.
2. Check the basis amount (net of tax and excluded items).
3. Check the channel and account status at the time.

### 8.4 Adjustments and approval

| Step | Who |
| --- | --- |
| Create an adjustment: account, ± points, reason, remarks, optional expiry | Any staff role (cashier, manager) |
| Up to the threshold, made by a Loyalty Manager | Posted immediately |
| Above the threshold, or made by a non-manager | **Pending Approval** |
| **Approve & Post** or **Reject** (with a reason) | Loyalty Manager |

**[System]**
- The adjustment records who requested it, who approved it, and when.
- Once posted, it links to its ledger entry.
- A posted adjustment is never edited. To fix a mistake, post an opposite adjustment.

### 8.5 Monitoring jobs and health

| Job | When | What to check if something looks wrong |
| --- | --- | --- |
| Campaign status | Every 10 min | Campaign stuck in Scheduled → is the scheduler running? |
| Wallet retries | Every 5 min | Wallet Pass → *Last Error*, *Retry Count* |
| Release pending points | Hourly | Pending points past their date |
| Missed-award backstop | Hourly | Paid orders without points |
| Expire points | 00:30 daily | Expiry Forecast report |
| Tier review | 02:00 daily | Tier Change log |
| Wallet reconcile | 03:00 daily | Wallet Pass sync times |
| Expiry notices, birthdays | 09:00 daily | Notification Log |
| Liability true-up | 23:50 daily | Liability Run (Posted / No Change / Failed) |
| Balance cache reconcile | Weekly | Error log entries report any drift |

Settings → Accounting also has a **Post Liability True-up Now** button for month-end.

---

## 9. Business rules and edge cases

### 9.1 Duplicate events and double processing **[System]**

- Every ledger write has a deterministic **idempotency key** (for example
  `earn:<invoice>:<rule>`), backed by a unique database index.
- Effect: a retried hook, a replayed job, a double tap or a network retry can never
  post twice. The second attempt finds the first.
- Events are de-duplicated per (event, customer, reference). On top of that, the event
  type's *once per customer* and *cooldown* rules apply.
- Reward purchases are de-duplicated by the client's `Idempotency-Key`.
- Notifications are sent once per key.

### 9.2 Concurrent redemptions **[System]**

- Every spend **locks the member's account row** for the rest of the database
  transaction. Two devices spending at the same moment are processed one after the
  other, and the second sees the reduced balance.
- **Online card checkout:**
  - When payment starts, the order's points and gift card amounts are **held**. Other
    orders and rewards see only what is left.
  - If the points or card balance were already spent, checkout is refused *before*
    charging the card.
  - The hold ends when the order is paid or abandoned (stale orders are cleaned up
    every 20 minutes).
- **Backstop:** if the card *was* charged but the points somehow fell short, the order
  still completes. The shortfall is recorded as **outstanding debt** on the member,
  repaid from future earning. A gift card overdraw is recorded and logged for review.
  The customer is never charged and then left without an order.

### 9.3 Insufficient balance

Applying more points than available is refused with the actual available figure. The
app should re-read `redemption_options` and let the member choose again.

### 9.4 Expired points

- Expired points cannot be spent. Spending always uses the soonest-expiring points first.
- Points returned by a refund keep their original expiry, plus grace days if that date
  has passed.

### 9.5 Cancellations and partial refunds

See section 5.5. Also:
- Cancelling an order forgives any outstanding debt that order created.
- Refund handling works whether the earned points are still pending or already available.

### 9.6 Duplicate customer accounts

- **[System]** One loyalty account per customer, and one per member number.
- **Gap:** if the same person exists as **two ERPNext customers** (e.g. they signed up
  online with a different email than at the counter), they get two loyalty accounts.
  There is no merge tool yet.
- Interim procedure **[Recommendation]**:
  1. Pick the account to keep.
  2. Post a negative *Migration* adjustment on the other.
  3. Post a matching positive adjustment on the kept one.
  4. Close the other account.
  5. Merge the customers in ERPNext if appropriate.

> ⚠ **Decision to confirm:**
> - Should merging accounts be a supported feature?
> - Which balance, tier and history win when two accounts merge?

### 9.7 Campaign conflicts

- Stackable campaigns combine. Of the non-stackable ones, only the highest priority wins.
- Inside one rules table, an *exclusive* rule stops lower-priority rules.
- Budgets and per-customer caps are enforced per award. The last order may receive a
  partial bonus when the budget runs out.
- A campaign's "live" check uses the order's time. Overnight weekly windows (e.g. Fri
  22:00 → Sat 02:00) count Saturday 01:00 as Friday's window.

> ⚠ **Decision to confirm:** the default for new campaigns is *stackable*. Should
> promotions stack, or should only the best one apply?

### 9.8 Other scenarios

| Scenario | Behaviour |
| --- | --- |
| Customer orders before joining | Enrolled on the first order (if on), and that order earns. Orders before the programme existed do not earn (no backfill); use an adjustment for goodwill. |
| Order paid in several payments | Earns once, when fully paid. |
| Points pay part of the order | That part does not earn, by default. |
| Gift card bought | Does not earn, by default. Spending the gift card on food does. |
| Third-party marketplace order | No earn, no redeem. |
| Member suspended mid-checkout | Redemption refused; the order can still be paid by other means. |
| Programme paused | No earning or redemption. Balances kept, and they still expire. |
| Programme point value changed | Applies to future redemptions. Existing balances are worth the new value; the liability follows at the next true-up. ⚠ *Decision to confirm:* how to announce value changes to members. |
| Lost phone / screenshot shared | Reissue the pass. The old QR is refused at lookup. |
| Birthday on Feb 29 | Celebrated on Feb 28 in non-leap years. |
| Wallet push fails | Marked failed, retried, and reconciled nightly. Devices that uninstalled the pass are cleaned up. |
| Event sent twice by an integration | Second one ignored (same reference). |

---

## 10. Security, permissions and audit

### 10.1 Roles

| Role | Can do |
| --- | --- |
| **System Manager** | Everything |
| **ArcPOS Loyalty Manager** | Settings, programme, campaigns, rewards, segments, event types; approve adjustments; reissue passes; view everything; call the events API |
| **ArcPOS Manager / Restaurant Manager** | Read programme, campaigns and rewards; look up members; apply points; create adjustments; reissue passes |
| **Restaurant Cashier / ArcPOS Register User / Restaurant Waiter** | Look up members, enrol, apply points, request step-up codes, create adjustments (go to approval) |
| **Accounts Manager / Accounts User** | Read transactions, liability runs, adjustment audit; post the true-up |
| **Customer (website user)** | Only their own account, through the customer endpoints |

### 10.2 Transaction integrity **[System]**

- **Ledger:**
  - Rows are never edited or deleted.
  - Corrections are new rows (Reverse, Adjust) that point at what they correct.
  - The only fields that move after insert are a lot's remaining points and status,
    and a debit's outstanding debt. Each such change is evidenced by an allocation row
    or a new entry.
- **Balances** shown to members are a cache. They are rebuilt from the ledger on
  demand and checked weekly.
- **Locks:**
  - Spending locks the account.
  - Gift cards are locked in a fixed order, so two orders cannot deadlock.
- **Idempotency** as in section 9.1.

### 10.3 Fraud prevention

| Threat | Control |
| --- | --- |
| A customer spending someone else's points | Customer endpoints take the member from the session, never from a parameter. |
| A forged or copied QR code | The token is HMAC-signed with a server secret. It identifies but cannot authorise a spend. A reissue invalidates old copies. |
| A cashier redeeming a member's points without them | Step-up code sent to the member, for exactly the amount, valid 5 minutes, with attempts limited. |
| A cashier inflating balances | Adjustment threshold and manager approval; audit report. |
| Brute force / scraping | Rate limits on lookup (60/min), redeeming rewards (10/min), applying points (20/min), wallet links (10/min); OTP send and attempt limits. |
| Wallet endpoint abuse | Apple passes authenticate with a per-pass token (stored hashed). Google callbacks are verified with Google's signature and a secret. |
| Leaked credentials | Wallet keys must be private files. Secrets are stored as encrypted password fields. |
| Self-dealing with returns | The return window (pending days) delays spendability; refunds take back points pro rata. |
| Abuse of sign-up bonuses | Once-per-customer events; excluded customers; consider a modest sign-up bonus. **[Recommendation]** |

### 10.4 Audit trail

| What | Where |
| --- | --- |
| Every point movement, with source document, rule, campaign, reward, event and remarks | Loyalty Transaction |
| Who adjusted, who approved, when, why | Loyalty Adjustment + *Loyalty Adjustment Audit* report |
| Tier history | Loyalty Tier Change |
| Notifications sent and failures | Loyalty Notification Log |
| Liability postings | Loyalty Liability Run + Journal Entries |
| Wallet sync state and errors | Wallet Pass |
| Settings and programme changes | Frappe version history on each document |

> ⚠ **Decision to confirm:**
> - How long is loyalty data retained?
> - How are privacy/deletion requests handled? The ledger is financial evidence and
>   should be anonymised rather than deleted.

---

## 11. Reporting and analytics

### 11.1 Built-in reports (Desk → Loyalty → Reports)

| Report | Answers |
| --- | --- |
| **Loyalty Points Summary** | Points earned, bonus, redeemed, expired, reversed and adjusted over a period |
| **Loyalty Liability** | Outstanding points and their value: what the business owes members |
| **Customer Loyalty Balances** | Per-member balances, tier and activity |
| **Loyalty Redemption Activity** | Points spent on orders and rewards, by period and channel |
| **Loyalty Campaign Performance** | Points issued, participants and orders per campaign |
| **Loyalty Expiry Forecast** | Points due to expire in coming periods |
| **Loyalty Adjustment Audit** | All manual adjustments, with requester and approver |

Every report can be filtered, saved and exported to Excel/CSV through the standard
report view.

### 11.2 Key metrics to track **[Recommendation]**

| Area | Metric | How to read it |
| --- | --- | --- |
| Engagement | Active members (ordered in the last 90 days) / total members | Is the programme alive? |
| Engagement | Enrolment rate (new members / new customers) | Is joining easy? |
| Behaviour | Visit frequency and average order value, members vs non-members | Does the programme change behaviour? |
| Points flow | Points issued, redeemed, expired per month | Is the economy balanced? |
| Points flow | **Redemption rate** = redeemed / issued | Too low: rewards aren't attractive. Too high: costs climb. |
| Points flow | **Breakage** = expired / issued | Points never used; reduces cost but can annoy customers. |
| Finance | Outstanding liability and its trend | What the business owes |
| Finance | Programme cost = value of redeemed points + reward vouchers | Cost of the programme |
| Campaigns | Incremental orders and points per campaign; cost per extra order | Did the campaign pay off? |
| Tiers | Members per tier, upgrades and downgrades | Are tier thresholds right? |
| Expiry | Points expiring next 30/90 days | Plan reminder campaigns |
| Wallets | Passes installed per platform | Wallet adoption |

> ⚠ **Decision to confirm:** which of these metrics management wants on a regular
> dashboard, and whether a BI tool will be used for comparisons of members vs
> non-members (those comparisons need a custom report or BI query).

### 11.3 Liability accounting

The liability is moved to match the ledger by a periodic **true-up** Journal Entry, so
there are not thousands of small accounting entries:

```
target  = (available + pending points) × point value
balance = current balance of the Liability account
delta   = target − balance   → Dr Expense / Cr Liability (or the reverse when it shrinks)
```

**[System]** behaviour:
- Redeeming points as payment debits the liability through the order's payment.
- Expired points simply drop out of the target at the next run.
- Every run is logged in *Loyalty Liability Run*.

---

## 12. Technical architecture and data model

### 12.1 Components

```
┌────────────── Clients ──────────────┐     ┌───────── External ─────────┐
│ order-web   mobile app   pos-web    │     │ Google Wallet API          │
│ (customer)  (customer)   (staff)    │     │ Apple APNs / PassKit       │
└───────┬───────────┬──────────┬──────┘     │ Moneris (card payments)    │
        │ /api/method/api.loyalty.*         │ Expo push                  │
        ▼                                   └────────────┬───────────────┘
┌──────────────────────── Frappe / ERPNext (excel_restaurant_pos) ────────┐
│ api/loyalty/        customer.py · staff.py · wallet.py · events.py      │
│ shared/loyalty/                                                         │
│   settings   accounts (enrol, tokens)   rules (engine)   campaigns      │
│   earning    redemption  holds  otp     rewards          events         │
│   ledger (lots, locks, idempotency)     reversal         expiry  tiers  │
│   segments   notifications              accounting       dashboard      │
│   wallet/ base · google · apple · apple_webservice · sync               │
│ Hooks: Sales Invoice validate/submit/cancel, Payment Entry submit,      │
│        Coupon Code update, Feedback update, scheduler jobs              │
└──────────────┬──────────────────────────────────┬───────────────────────┘
               ▼                                  ▼
          MariaDB (ledger, accounts)        Redis (OTP, rate limits,
                                            wallet debounce, caches, jobs)
```

### 12.2 Data model

| Entity (DocType) | Key fields | Relationships |
| --- | --- | --- |
| **ArcPOS Loyalty Settings** (single) | enabled, active programme, accounts, thresholds, wallet credentials, branding | → Programme |
| **ArcPOS Loyalty Programme** | point value, earn basis/timing, pending days, redemption limits, expiry, tiers, base rules | has Tiers, Rules, Rule Items |
| **ArcPOS Loyalty Account** | member number (unique), customer (unique), user, status, tier, cached balances, lifetime totals, token version, preferences | → Customer, User, Programme |
| **ArcPOS Loyalty Transaction** | type (Earn/Bonus/Redeem/Expire/Reverse/Adjust), points (signed), status, expiry, remaining points, outstanding debt, source document, campaign, rule, reward, event, idempotency key (unique), basis amount/items | → Account; has Allocations (which lots a debit used); `reverses` → Transaction |
| **ArcPOS Loyalty Campaign** | window, recurrence, eligibility (channels, tiers, segments, territories), budget, caps, priority, stackable, stats | has Rules, Rule Items |
| **ArcPOS Loyalty Rule** (child) | trigger, event type, rule type, points, per amount, multiplier, filters, priority, exclusive, condition | in Programme or Campaign |
| **ArcPOS Loyalty Event Type** | code, once per customer, cooldown | ← Rules |
| **ArcPOS Loyalty Segment** | filters or static members | ← Campaigns |
| **ArcPOS Loyalty Reward** | type, cost, discount, free item, validity, limits | issues Coupon Code |
| **ArcPOS Loyalty Adjustment** (submittable) | points, reason, approval fields | → Transaction |
| **ArcPOS Loyalty Tier Change** | from/to tier, reason | → Account |
| **ArcPOS Loyalty Notification Log** | kind, key, channels, error | → Account |
| **ArcPOS Loyalty Liability Run** | target, GL balance, delta, Journal Entry | → Programme |
| **ArcPOS Wallet Pass** | platform, object id, status, sync hash, retry state, auth token | → Account |
| **ArcPOS Wallet Device Registration** | device, push token | → Wallet Pass |
| **Sales Invoice** (custom fields) | `custom_loyalty_account`, `custom_loyalty_points_redeemed`, `custom_loyalty_redeem_value`, `custom_loyalty_points_earned`, `custom_loyalty_verified` | → Account |

### 12.3 The ledger: lots and allocations

- Every **credit** is a **lot**, with `remaining_points`, an `expiry_date` and a status
  (Pending → Available → Consumed / Expired / Reversed).
- Every **debit** consumes lots, earliest expiry first, and records exactly which lots
  it used in its **allocations**. This is what lets a refund restore exactly those
  points with their original expiry.
- A debit that cannot be fully covered (only possible on reversal or card-paid
  backstop) records **outstanding debt**. Future credits pay that debt first.

### 12.4 Event flows

**Earning**
```
Sales Invoice submitted / Payment Entry submitted
  → earning.on_invoice_submit / on_payment_settled
  → is the invoice paid (or "Earn On = Submitted")? member Active? channel allowed?
  → build context (lines, channel, time, tier, segments, order number)
  → rules.evaluate(base scope + live campaign scopes)
  → ledger.post_credit per award (idempotent; Pending if pending_days > 0)
  → tiers.evaluate → notifications.enqueue → wallet.schedule_sync
Hourly backstop: backfill_missed_awards
```

**Redemption on an order**
```
apply_points → validate limits & holds → reserve on draft (or spend now if submitted)
get_ticket → hold points & gift cards → Moneris charges amount_due
receipt_payment → claim ticket (redeemed_at) → submit invoice
  → redemption: ledger.post_debit (locked; allow negative only if card already paid)
  → Payment Entry with Loyalty Points mode of payment (debits liability)
```

**Reversal**
```
Invoice cancelled → reverse every entry it produced
Credit note submitted → reverse earned + restore redeemed, pro rata by returned lines
```

**Wallet**
```
any balance/tier/status change → schedule_sync (30 s debounce + dirty flag)
  → render view → Google PATCH object | Apple APNs push → device GETs new .pkpass
failures → retry every 5 min; reconcile all nightly
```

### 12.5 Integration patterns **[System]** and **[Recommendation]**

- **Idempotency everywhere** a client can retry. Clients generate a UUID per user
  action and reuse it on retry.
- **After-commit side effects:** notifications and wallet syncs are queued only after
  the database commit, so a rolled-back order leaves no trace.
- **Never fail the order:** loyalty side effects are wrapped so their failure is
  logged, not raised, and backstop jobs complete the work.
- **Server is the source of truth:** clients display API results and never compute
  balances.
- **Extensibility:**
  - A new rule type is one function plus one select option.
  - A new event is one Event Type record plus an `emit` call.
  - A new channel is one entry in the channel map plus two checkboxes.

---

## 13. End-to-end workflows with examples

The examples use this setup:

| Setting | Value |
| --- | --- |
| Point value | 0.01 |
| Earning | Spend Rate 1 point per $1 net |
| Rounding | Floor |
| Pending days | 0 |
| Expiry | Fixed, 365 days |
| Tiers | Bronze ×1, Silver ×1.25 from $500 |
| Sign-up bonus | 5 points |

### 13.1 Customer registration

1. Maya creates an account on the website on 2 Mar.
2. The storefront links her user to a new Customer, and she is auto-enrolled. Account
   `LM-7Q2…`, tier Bronze.
3. The `customer_signup` event fires: **+5 points** (Bonus).
4. Her app shows 5 points ($0.05) and a QR code. She taps **Add to Apple Wallet**, and
   the pass appears with 5 points.

### 13.2 Purchase-based reward

1. 5 Mar: Maya orders online for delivery. Net $42.80, tax $5.56.
2. Checkout shows "You'll earn 42 points".
3. She pays by card. The order is submitted and paid.
4. Ledger: **Earn +42**, expiring 5 Mar next year. Balance 47.
5. She gets an email "You earned 42 points". Her wallet pass shows 47 within about 30
   seconds.

### 13.3 Product-specific promotion

**Setup:** campaign "Pizza Week", 10–16 Mar, rule Item Quantity 20 points, Rule Item:
Item Group *Pizza*.

1. 12 Mar: Maya orders 2 pizzas ($30) and a drink ($4) for pickup.
2. Ledger:
   - **Earn +34** (base: 1 point per $1 on $34)
   - **Bonus +40** ("Pizza Week", 2 × 20)
3. Balance 121.

### 13.4 Seasonal campaign with a multiplier

**Setup:** campaign "December weekends", Weekly `Sat,Sun`, 1–31 Dec, Multiplier ×2 on
Base Points, stackable.

1. Sat 6 Dec: Maya (now Silver) orders $60 net at the table.
2. The points are worked out as follows:

| Step | Ledger line | Points |
| --- | --- | --- |
| Base rule: 1 point per $1 on $60 | Earn | +60 |
| Silver tier ×1.25 on base points | Tier bonus | +15 |
| Campaign ×2 on base points (the 60, before the tier bonus) | Bonus — "December weekends" | +60 |
| **Total** | | **135** |

Each line is a separate ledger entry, so the member's history and the reports show
exactly where every point came from.

### 13.5 Point redemption at online checkout

1. Maya has 1,250 points. The order is $25.00 grand total. Programme limits: max 50%
   of the order, increment 100.
2. `redemption_options`: max = min(1,250, 50% of $25 = 1,250 points, rounded to the
   increment) = **1,200**.
3. She chooses 1,000 points = $10.00. "To pay: $15.00".
4. `get_ticket` holds the 1,000 points and charges $15.00 by card.
5. On payment the order is submitted:
   - **Redeem −1,000**, paid by the *Loyalty Points* payment method
   - **Earn** on the part of the order paid by card (since points-paid amounts don't earn)
6. Meanwhile her partner tries to use the same points on another phone. They see only
   250 available.

### 13.6 Redemption at the counter with step-up

1. Step-up threshold is 500. Maya is at the counter wanting to use 800 points.
2. The cashier scans her wallet pass QR. `lookup` shows Maya, `m***@g***.com`, 1,450
   points.
3. The cashier requests a code for 800 points. Maya gets "Code 482913 to use 800 points".
4. She reads it out, the cashier verifies it and applies the points. The receipt shows
   "800 points used ($8.00)".

### 13.7 Reward purchase

1. Maya buys "Free dessert — 300 points" in the app. The app sends an `Idempotency-Key`.
2. Her connection drops and the app retries with the same key. She gets the same
   voucher `RWD-…` back, and only 300 points are spent.
3. The voucher is valid 30 days and only on orders containing the dessert.
4. If she never uses it, it expires and the 300 points come back (setting on).

### 13.8 Partial refund

1. The order in 13.3 is partly refunded: the 2 pizzas are returned, the drink kept.
2. Credit note:
   - **Reverse −30** of the 34 base points (30/34 of the value)
   - **Reverse −40** of the Pizza Week bonus (all the matching lines were returned)
3. If Maya had already spent those points and *Allow Negative* is off, only what is
   left is taken back. If it is on, her balance can go negative and is repaid from her
   next earnings.

### 13.9 Full cancellation of an order that used points

1. An order where Maya used 500 points is cancelled.
2. **Reverse +500**: the points come back with their original expiry dates. Points
   whose expiry already passed get 7 grace days.
3. The points that order earned are taken back.

### 13.10 Wallet synchronisation

1. Maya has the pass in both Apple and Google Wallet.
2. She earns 42 points. One sync job is queued for her account.
3. **Google:** her pass object is updated, and her Android phone shows the new balance.
4. **Apple:** APNs pushes to her iPhone. The iPhone asks for the latest pass and
   downloads the updated version.
5. If APNs is down, the pass is marked failed and retried every 5 minutes. The 03:00
   reconcile catches anything left.
6. She loses her phone. The manager taps **Reissue Pass**:
   - Her old QR is refused at the counter.
   - Her wallet passes update with the new code.

### 13.11 Custom event from an external system

A survey tool calls `events.emit` with `event_code=survey_completed`,
`customer=CUST-00042` and `reference=survey-9f2c1`. A rule awards 25 points. The tool
retries after a timeout with the same reference, and no second award is made.

---

## 14. Testing and go-live checklist

### 14.1 Configuration checklist

- [ ] Migrations applied. *Loyalty Points* mode of payment and built-in event types exist.
- [ ] Liability and expense accounts created; true-up frequency chosen.
- [ ] Programme created with every ⚠ decision in section 15 answered; set to Active.
- [ ] Settings: programme, accounts, excluded customers, voucher pricing rule, email
  templates, thresholds; **Enabled** ticked.
- [ ] Sign-up and birthday rules (if wanted), first rewards, launch campaign.
- [ ] Scheduler running; Python dependencies installed.
- [ ] Wallets (if launching): credentials, branding, icon, web service URL reachable
  over HTTPS from the internet.
- [ ] Staff roles assigned; Loyalty Manager named.

### 14.2 Acceptance scenarios

| # | Area | Scenario | Expected |
| --- | --- | --- | --- |
| 1 | Enrol | New web sign-up | Account created, sign-up bonus once, visible in the app |
| 2 | Enrol | Sign-up then immediate first order (race) | One account only |
| 3 | Enrol | Walk-in customer at POS | Not enrolled, no points |
| 4 | Earn | Online order paid by card | Correct points; pending if pending days > 0 |
| 5 | Earn | Order submitted but unpaid (Earn On = Paid) | No points until paid |
| 6 | Earn | Uber Eats order | No points |
| 7 | Earn | Excluded item group / gift card | Those lines earn nothing |
| 8 | Rules | Item quantity rule on a category incl. sub-groups | Bonus per matching unit |
| 9 | Rules | Exclusive rule | Lower-priority rules skipped |
| 10 | Rules | Bad condition | Rejected on save; at runtime only that rule is skipped |
| 11 | Campaign | Weekly overnight window (22:00–02:00) | Live at 01:00 the next day; not at 03:00 |
| 12 | Campaign | Two non-stackable campaigns | Only highest priority applies |
| 13 | Campaign | Budget reached | Campaign ends; last award clamped |
| 14 | Campaign | Simulate on Order | Shows awards, writes nothing |
| 15 | Tier | Spend crosses threshold | Upgrade immediately; multiplier on next order; tier change logged |
| 16 | Redeem | Apply above max %, below min, off-increment | Refused with a clear message |
| 17 | Redeem | Two devices spend the same points | The second is refused / sees the reduced balance |
| 18 | Redeem | Points spent elsewhere after apply, before card payment | `get_ticket` refuses before charging |
| 19 | Redeem | Card charged, points short (backstop) | Order completes; outstanding debt recorded |
| 20 | Redeem | Points cover the whole order | `payment_required: false`, order submitted |
| 21 | Redeem | POS redemption above step-up | Requires the code; wrong code refused; code for another amount refused |
| 22 | Reward | Double tap / retry with the same key | One voucher, points spent once |
| 23 | Reward | Voucher expires unused | Points refunded (if on) |
| 24 | Refund | Full cancel | Earned taken back, redeemed restored with original expiry |
| 25 | Refund | Partial return of item-rule lines | Pro rata reversal; item bonus only for returned matching lines |
| 26 | Refund | Earned points already spent, negative off/on | Off: partial reversal; on: negative balance repaid by next earn |
| 27 | Expiry | Lot past expiry at 00:30 | Expired, ledger line, liability drops at true-up |
| 28 | Expiry | Notices | Sent once at 30/7/1 days |
| 29 | Events | `emit` twice with the same reference | One award |
| 30 | Events | Birthday on Feb 29, non-leap year | Awarded on Feb 28 |
| 31 | Adjust | Cashier adjustment over the threshold | Pending; manager approves/rejects; audit report shows both users |
| 32 | Security | Customer calls the API for another customer's order | 403 |
| 33 | Security | Reissued pass, old QR scanned | Lookup finds nothing |
| 34 | Wallet | Add to Google Wallet | Pass saved; app shows Installed |
| 35 | Wallet | Add to Apple Wallet (Safari and native) | Pass added; device registered |
| 36 | Wallet | Earn points | Both passes update within about a minute |
| 37 | Wallet | Uninstall pass on the iPhone | Registration removed; no further pushes |
| 38 | Wallet | APNs/Google outage | Retries, then success; nightly reconcile |
| 39 | Accounting | Daily true-up | Journal Entry = target − GL balance; run logged |
| 40 | Accounting | Points as payment | Payment Entry debits the liability |
| 41 | Disabled | Settings Enabled off | No loyalty UI, no earning or redemption anywhere |

### 14.3 Per-application checks

- **Web (order-web):** loyalty home, join, history paging and filters, campaigns,
  rewards, checkout slider, `amount_due` charged, error messages shown as-is, wallet
  buttons only when enabled.
- **Mobile app:** the same, plus push notifications received, native Apple pass
  download, Google save link, QR refresh on app open.
- **POS / desktop:** scan QR from the app and from both wallets, search by phone/email,
  enrol, apply/remove points, step-up, receipt fields, payments rows add up to
  `grand_total − loyalty value`, adjustments.
- **Desk:** every report runs; workspace cards match the reports; Recompute Balance
  changes nothing on a healthy account.

### 14.4 Automated tests in the repository

Run them with `bench --site <site> run-tests --module <module>`:

- `excel_restaurant_pos.shared.loyalty.test_units`
- `excel_restaurant_pos.shared.loyalty.test_rules`
- `excel_restaurant_pos.shared.loyalty.test_loyalty_flow`
- `excel_restaurant_pos.shared.loyalty.test_wallet`
- `excel_restaurant_pos.shared.gift_card.test_gift_card_holds`

### 14.5 Go-live plan **[Recommendation]**

1. Run on a staging site with real menu data for one week, using staff accounts.
2. Soft launch: enable, with no marketing, at one location or channel.
3. Check the first daily true-up, expiry run and wallet reconcile.
4. Announce to customers. Run a launch campaign with a capped budget.
5. Review the metrics in section 11.2 after 30 days and tune the rules.

---

## 15. Decisions to confirm

Each item has a working default in the system. The business must confirm or change it
before launch.

| # | Decision | System default | Owner |
| --- | --- | --- | --- |
| 1 | Point value (what 1 point is worth) | 0.01 (100 points = $1) | Business / Finance |
| 2 | Base earn rate | Set by admin, e.g. 1 point per $1 | Business |
| 3 | Earn on net (before tax) or grand total | Net | Business / Finance |
| 4 | Earn when paid or when submitted | Paid | Business |
| 5 | Return window before points are spendable | 0 days | Business |
| 6 | Expiry mode and period | Fixed 365 days per lot | Business / Legal |
| 7 | Expiry notice days | 30, 7, 1 | Business |
| 8 | Minimum / maximum / % / increment for redemption | 0 / unlimited / 100% / 1 | Business |
| 9 | Negative balances on refunds of spent points | Off | Business / Finance |
| 10 | Tiers: names, thresholds, multipliers, basis, downgrade policy | None until defined | Business |
| 11 | Sign-up, first-order and birthday bonuses | None until rules are added | Marketing |
| 12 | Which channels earn and redeem | All four direct channels | Business |
| 13 | Third-party marketplace orders | Never earn or redeem | Business (changing it is a code change) |
| 14 | Points with coupons and gift cards on the same order | Allowed | Business |
| 15 | Campaigns stack by default | Yes | Marketing |
| 16 | Step-up verification threshold at the POS | Off | Operations / Risk |
| 17 | Adjustment approval threshold | 500 points | Operations / Finance |
| 18 | Refund points for expired reward vouchers | Yes | Business |
| 19 | Explicit consent to join vs automatic enrolment | Automatic | Legal / Marketing |
| 20 | Closing accounts, data deletion and retention | Not defined | Legal |
| 21 | Duplicate customer merge policy | Manual workaround only | Operations |
| 22 | Liability true-up frequency and accounts | Daily | Finance |
| 23 | Wallet launch (Apple, Google, both) and certificate ownership | Off | Business / IT |
| 24 | Separate desktop application? | pos-web only | IT |
| 25 | Backfill points for orders before launch | No backfill | Business |
| 26 | Communicating a point value change to members | Not defined | Marketing |
| 27 | Management dashboard metrics and BI tooling | Built-in reports only | Management |

---

## 16. Known gaps and future enhancements

| Item | Status | Notes |
| --- | --- | --- |
| Merging duplicate loyalty accounts | Not built | Manual adjustment workaround (section 9.6) |
| Referral programme | Event type exists; no built-in emitter | An integration or a future feature must call `emit('referral', …)`, e.g. when the referred friend's first order is paid |
| SMS notifications | Not built | Email and Expo push only |
| Member vs non-member comparison analytics | Not built | Custom report or BI |
| Gift card balance after an order cancel | To verify | Check whether cancelling an order paid partly by gift card restores the card balance |
| Multiple simultaneous programmes (brands) | One active programme per site | Data model supports several programmes; settings select one |
| Points transfer between members / family pooling | Not built | Would need a new transaction type and rules |
| Paid membership tier / subscriptions | Not built | Would build on tiers |
| Partner earning (earn at partner businesses) | Possible via `emit` with `payload.amount` | Needs a partner agreement and an API key |

---

## 17. Glossary

| Term | Meaning |
| --- | --- |
| **APNs** | Apple Push Notification service: how the backend tells iPhones a pass changed |
| **Breakage** | Points that expire unused |
| **Credit note** | A return / refund document against a sales invoice |
| **Debounce** | Combining many quick changes into one update |
| **Draft order** | An order not yet submitted (e.g. a cart in checkout) |
| **HMAC** | A signature made with a secret key; it proves a value was created by the server |
| **Idempotency key** | A unique label for an action, so repeating it has no extra effect |
| **Journal Entry** | An accounting entry in ERPNext |
| **Liability** | Money the business owes; here, the value of unspent points |
| **Lot** | One batch of credited points with its own expiry |
| **Member token** | The signed code in the QR and wallet pass that identifies a member |
| **Mode of Payment** | A payment method in ERPNext (Cash, Card, Loyalty Points…) |
| **Moneris** | The card payment gateway used for online checkout |
| **Payment ticket** | The gateway session created when online card checkout starts |
| **PassKit** | Apple's wallet pass system |
| **Pro rata** | In proportion; a 50% refund takes back 50% of the points |
| **Segment** | A defined group of members, by filters or a fixed list |
| **Step-up verification** | An extra one-time code required for large redemptions |
| **Tier** | Membership level with its own earn multiplier and benefits |
| **True-up** | Adjusting the accounts to match the real outstanding amount |
