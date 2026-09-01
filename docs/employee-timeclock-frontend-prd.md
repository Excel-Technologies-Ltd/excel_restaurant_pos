# Employee Timeclock — Frontend Integration PRD

**Product:** ArcPOS (POS client)
**Feature:** Employee Timeclock — PIN check in / check out, and manager overrides
**Backend:** shipped in `excel_restaurant_pos` (`api.timeclock.*`). API reference: [`employee-timeclock-api.md`](./employee-timeclock-api.md)
**Status:** Ready for frontend implementation
**Owner:** POS frontend

---

## 1. Summary

Staff clock in and out on the POS with a 6-digit PIN — no user account, no login switch. One record per employee per business day holds the first check in and the last check out; paid hours and payment are derived from those two timestamps. Managers fix mistakes (missed check out, wrong time, a day never clocked) from the same menu behind a Manager PIN.

### Goals

1. A waiter can clock in or out in **≤ 3 taps** from the POS menu (menu → PIN → action).
2. The POS never decides *which* action is allowed — the backend returns it. The UI renders state.
3. A manager can repair any day's record without leaving the POS or opening Desk.
4. A PIN never leaves memory: not persisted, not logged, not sent to analytics.

### Non-goals

- Shift scheduling, breaks, overtime rules, payroll export.
- Showing an employee their own wage or total payment (manager-only data).
- Offline clock in / out (see §10).

---

## 2. Roles

| Role | Source | Can do |
|------|--------|--------|
| Employee | `ArcPOS Employee.role` ∈ `Waiter`, `Barista`, `Cashier`, `Manager` | Check in / check out with own PIN |
| Manager | `ArcPOS Employee.role = Manager` | Everything above, plus **Timeclock Edit** and **Add** |

A Manager is also an ordinary employee — they clock in with the same numpad. `authenticate` returns `is_manager` so the UI may reveal manager options right after a PIN entry, but **every manager action re-sends a Manager PIN**; there is no server-side session for it.

---

## 3. Core rules the UI must respect

| Rule | Behaviour |
|------|-----------|
| **Business day** | 04:01 AM (day T) → 04:00 AM (day T+1). A check out at 02:00 belongs to the *previous* calendar date. Never compute this in the client — use `business_date` from the response. |
| **One record per day** | Check in writes `first_check_in` once. Every later check out **replaces** `last_check_out` until the 04:00 cutoff. |
| **Blocked entry** | If an *earlier* business date has no check out, the employee cannot start a new entry until a manager fixes it. Backend returns `action: "blocked"`. |
| **Server time is truth** | Timestamps are written by the server. The client never sends "now". Do not localize or shift returned datetimes (see §9). |
| **Wage is manager-only** | `timeclock_cost` / `total_payment` come back on every record. Render them **only** inside manager screens. |

---

## 4. Entry points

POS menu → **Employee Timeclock** opens the Timeclock modal. The modal has one primary surface (numpad) and two manager options:

```
┌──────────── Employee Timeclock ────────────┐
│                                       [ X ]│
│              Enter your PIN                │
│            ● ● ● ● ○ ○                     │
│        ┌───┐ ┌───┐ ┌───┐                   │
│        │ 1 │ │ 2 │ │ 3 │                   │
│        │ 4 │ │ 5 │ │ 6 │                   │
│        │ 7 │ │ 8 │ │ 9 │                   │
│        │ ⌫ │ │ 0 │ │ ✓ │                   │
│        └───┘ └───┘ └───┘                   │
│                                            │
│   Timeclock Edit            Add            │  ← both Manager-PIN gated
└────────────────────────────────────────────┘
```

---

## 5. Flow A — Employee check in / check out

### A1. PIN entry

- 6 digits, numeric only. Auto-submit on the 6th digit (no separate confirm needed; keep `⌫`).
- Mask entered digits as dots. Disable copy/paste, autofill, and screenshot-friendly plain rendering.
- On submit → `POST api.timeclock.authenticate { pin }`, show a spinner on the numpad, block re-submit.
- On any error → shake the dots, clear the field, keep the modal open, show the server message.

### A2. Action screen

Render from the `authenticate` response. `action` decides everything; `can_check_in` / `can_check_out` are convenience booleans for button state.

```
┌──────────── Employee Timeclock ────────────┐
│  Aisha Rahman · Waiter                [ X ]│
│  Business day: 01 Sep 2026                 │
│                                            │
│  Checked in    09:05 AM                    │  ← only when record exists
│  Checked out   —                           │
│                                            │
│        [   Check Out   ]                   │  ← single primary action
└────────────────────────────────────────────┘
```

| `action` | Primary button | Secondary state |
|----------|----------------|-----------------|
| `check_in` | **Check In** (enabled) | No record yet — hide the times block |
| `check_out` | **Check Out** (enabled) | Show `first_check_in`; show `last_check_out` if set, with helper text "Checking out again updates your check-out time." |
| `blocked` | Both actions **disabled** | Render `message` as a warning, plus `open_record.business_date`, and the hint "Ask a manager to fix it under Timeclock Edit." |

Only ever render one primary action. Do not show a disabled "Check In" next to an enabled "Check Out".

### A3. Confirm

- Tap → `POST api.timeclock.check_in` / `api.timeclock.check_out` with the **same PIN held in memory**.
- Success → success screen for ~2s with the written time, then auto-close the modal:
  `Checked in at 09:05 AM` / `Checked out at 05:40 PM · 8.58 h today`
  (`total_paid_hours` is decimal hours — format as `8h 35m`.)
- Then discard the PIN from memory.

### A4. State machine

```
        PIN ✓
  idle ───────► authenticated ──┬── action=check_in  ──► [Check In]  ─► success ─► close
                                ├── action=check_out ──► [Check Out] ─► success ─► close
                                └── action=blocked   ──► warning only ─────────────► close
        PIN ✗ / throttled ──► error toast, stay on numpad
```

---

## 6. Flow B — Manager: Timeclock Edit

Fixing an existing record (forgot to check out, wrong time).

### B1. Unlock

- Tap **Timeclock Edit** → same numpad, header copy "Manager PIN required".
- `POST api.timeclock.manager_authenticate { manager_pin }` → returns `manager` and the `employees` list for the dropdown (already filtered to active employees, sorted by name).
- Non-manager PIN → `403 PermissionError`, message "This action requires a Manager PIN". Stay on the numpad.
- **Hold the manager PIN in memory for the panel session only.** Auto-lock (drop the PIN, return to the numpad) after **5 minutes idle** or when the modal closes.

### B2. Filter panel

```
┌──────────── Timeclock Edit ────────────────┐
│  Manager: Karim                       [ X ]│
│  Employee  [ Aisha Rahman        ▾ ]       │
│  Date      [ 01 Sep 2026        📅 ]       │
│                       [   Fetch Record  ]  │
└────────────────────────────────────────────┘
```

- Employee options come from `employees` (`employee` = id, `employee_name` = label).
- Date picker defaults to the current business date; **future dates disabled**.
- **Fetch Record** → `POST api.timeclock.get_record { manager_pin, employee, business_date }`.

### B3. Record form

- `record: null` → empty state: "No timeclock entry for Aisha Rahman on 01 Sep 2026." with a **Create Entry** button that carries employee + date into Flow C.
- `record` present → editable form:

```
┌──────────── Timeclock Edit ────────────────┐
│  Aisha Rahman · 01 Sep 2026           [ X ]│
│  First check in   [ 01 Sep 2026 09:05 ]    │
│  Last check out   [ 01 Sep 2026 17:40 ]    │
│  Total hours      8h 35m           (auto)  │
│  Hourly rate      $12.00                   │
│  Total payment    $103.00          (auto)  │
│  ⓘ Edited by manager Karim                 │  ← when is_modified = 1
│                        [ Cancel ] [ Save ] │
└────────────────────────────────────────────┘
```

- Total hours / total payment are **read-only**; recompute locally for instant feedback, then replace with the saved values from the response.
- Client validation before save: check out ≥ check in; check in required. Save disabled until something changed.
- **Save** → `POST api.timeclock.update_record { manager_pin, employee, business_date, first_check_in, last_check_out }`.
  - Omit a key → unchanged. Send `""` → clear it (used to reopen a day). Clearing `first_check_in` is rejected by the server.
  - Response record carries `is_modified: true` and `modified_by_manager` — reflect both in the UI.
- Success toast: "Timeclock updated for Aisha Rahman — 01 Sep 2026."

---

## 7. Flow C — Manager: Add (manual entry)

For a business date the employee never clocked.

- Entry: **Add** in the Timeclock modal, or **Create Entry** from the B3 empty state.
- Manager PIN unlock is identical to B1 (reuse the in-memory PIN if the panel is already unlocked).

```
┌──────────────── Add Entry ─────────────────┐
│  Employee       [ Aisha Rahman       ▾ ]   │
│  Date           [ 31 Aug 2026       📅 ]   │
│  First check in [ 31 Aug 2026 09:00  🕘 ]  │
│  Last check out [ 31 Aug 2026 17:00  🕘 ]  │
│  Total hours    8h 00m              (auto) │
│                        [ Cancel ] [ Save ] │
└────────────────────────────────────────────┘
```

- `first_check_in` required; `last_check_out` optional (leaving it empty creates an open record — warn: "This day will stay open until a check out is recorded.").
- Date defaults to the previous business date; future dates disabled.
- **Save** → `POST api.timeclock.add_entry`. The record comes back with `manual_entry: true`.
- Duplicate for that employee/date → server rejects; offer "Open in Timeclock Edit" in the error state.

---

## 8. API contract summary

All routes are `POST`, require the normal POS session auth, and wrap the payload in `message`.

| Screen / action | Route | Body |
|---|---|---|
| PIN submit | `api.timeclock.authenticate` | `pin` |
| Check In | `api.timeclock.check_in` | `pin` |
| Check Out | `api.timeclock.check_out` | `pin` |
| Manager unlock | `api.timeclock.manager_authenticate` | `manager_pin` |
| Refresh dropdown | `api.timeclock.employees` | `manager_pin`, `include_inactive?` |
| Fetch record | `api.timeclock.get_record` | `manager_pin`, `employee`, `business_date` |
| Save edit | `api.timeclock.update_record` | `manager_pin`, `employee`, `business_date`, `first_check_in?`, `last_check_out?` |
| Save manual entry | `api.timeclock.add_entry` | `manager_pin`, `employee`, `business_date`, `first_check_in`, `last_check_out?` |

**`record` object** (same shape everywhere it appears, `null` when no record exists):

```json
{
  "name": "ETT-2026-09-01-7",
  "employee": 7,
  "employee_name": "Aisha Rahman",
  "business_date": "2026-09-01",
  "first_check_in": "2026-09-01 09:05:00",
  "last_check_out": "2026-09-01 17:40:00",
  "total_paid_hours": 8.58,
  "timeclock_cost": 12.0,
  "total_payment": 103.0,
  "is_modified": false,
  "manual_entry": false,
  "modified_by_manager": null
}
```

Note: the audit field is `modified_by_manager` (not `modified_by`, which is a reserved Frappe column).

---

## 9. Data formats

| Field | Format | Client handling |
|-------|--------|-----------------|
| `pin`, `manager_pin` | string of exactly 6 digits | Keep as string — leading zeros matter. |
| `employee` | integer id | Use as the dropdown value; label with `employee_name`. |
| `business_date` | `YYYY-MM-DD` | Send exactly this; never derive it from the device clock. |
| `first_check_in`, `last_check_out` | `YYYY-MM-DD HH:mm:ss`, **server local time, no timezone suffix** | Parse as naive local time. Do **not** `new Date(str)`-then-convert, and do not send ISO strings with `Z`. |
| `total_paid_hours` | decimal hours, 2 dp (`8.58`) | Render as `8h 35m`. |
| `timeclock_cost`, `total_payment` | currency float | Manager screens only. |

---

## 10. Error handling

| Case | Server | UI |
|------|--------|----|
| PIN not 6 digits | 417 `ValidationError` | Inline: "PIN must be 6 digits." Never reaches the server if client-validated. |
| Wrong / inactive PIN | 401 `AuthenticationError` | "Invalid PIN." Clear dots, stay on numpad. Never reveal whether the PIN exists. |
| >10 failed PINs in 5 min (per user + IP) | 401 `AuthenticationError` | "Too many attempts. Try again in a few minutes." Disable the numpad for 60s. |
| Non-manager PIN on a manager route | 403 `PermissionError` | "This action requires a Manager PIN." |
| Already checked in | 417 | Re-fetch `authenticate` and re-render — the state was stale. |
| Not checked in yet (check out) | 417 | Same: re-fetch and re-render. |
| Earlier day still open | 417 | Blocked warning with the open date and the manager hint. |
| Record missing on edit | 417 `DoesNotExistError` | Empty state with **Create Entry**. |
| Duplicate on add | 417 `DuplicateEntryError` | "An entry already exists for this date." → **Open in Timeclock Edit**. |
| Check out before check in | 417 | Inline field error on `last_check_out`. |
| Network failure / timeout | — | "Couldn't reach the server. Try again." **Never** optimistically show a successful clock in — there is no offline queue; a retry after an unclear failure is safe because check out is idempotent-by-replacement, while a duplicate check in is rejected by the server. |

Read messages from Frappe's `_server_messages` / `exception` exactly as the gift card and coupon flows already do.

---

## 11. Non-functional requirements

**Security**
- PIN lives in component memory only: no `localStorage`, `sessionStorage`, cookies, URL params, Redux persistence, Sentry breadcrumbs, or analytics payloads.
- Clear the PIN on: successful action, modal close, route change, app background, 5-minute idle lock.
- Numpad input masked; disable browser autofill/password-manager hooks on the field.
- Manager panels re-send the PIN per request — treat the panel as a short-lived unlocked state, not a session.

**Usability**
- Touch targets ≥ 56×56 px; the modal must work one-handed on the POS tablet in both orientations.
- All state changes announce to screen readers (`aria-live` on the action/status region); numpad keys are real buttons with labels.
- Hardware numeric keypad input mirrors the on-screen numpad.

**Performance**
- `authenticate` → action screen in < 500 ms p95 on the venue network; spinner after 150 ms.
- Employee dropdown is fetched at unlock, cached for the panel session, refreshable via `api.timeclock.employees`.

---

## 12. Acceptance criteria

1. **Given** an employee with no entry for the current business date, **when** they enter a valid PIN, **then** only **Check In** is enabled, and tapping it stores `first_check_in` and closes the modal with a confirmation.
2. **Given** an employee already checked in, **when** they authenticate, **then** only **Check Out** is enabled, and each tap replaces `last_check_out` and updates the displayed total hours.
3. **Given** it is 02:00 AM, **when** an employee checks out, **then** the UI shows the *previous* calendar date as the business day, taken from the response.
4. **Given** an employee's earlier business date has no check out, **when** they authenticate, **then** both actions are disabled and the blocking date plus the manager hint are shown.
5. **Given** a non-manager PIN, **when** it is entered on **Timeclock Edit** or **Add**, **then** access is refused and no employee list is rendered.
6. **Given** a manager fetched a record, **when** they change the timestamps and save, **then** the response shows recalculated hours, `is_modified = true`, and the manager in `modified_by_manager`, and the UI reflects all three.
7. **Given** a business date with no record, **when** a manager saves an **Add** entry, **then** the record returns with `manual_entry = true` and appears in **Timeclock Edit** for that date.
8. **Given** any screen, **when** the modal is closed or 5 minutes pass idle, **then** the PIN is no longer in memory and re-entry is required.
9. **Given** 11 consecutive invalid PINs, **when** the 11th is submitted, **then** the throttle message is shown and the numpad is temporarily disabled.
10. **Given** wage data in a response, **when** the employee-facing screens render, **then** neither `timeclock_cost` nor `total_payment` is displayed anywhere.

---

## 13. Out of scope / follow-ups

- Offline clock in / out queue.
- An employee-facing "my hours this week" view (needs a new list endpoint).
- Manager view of *all* open records across employees (currently one employee/date at a time).
- Payroll export and approval workflow on timeclock entries.

## 14. Open questions

1. Should the Timeclock modal be reachable from the lock screen (before a POS user logs in), or only inside an authenticated POS session? The API requires an authenticated session today.
2. Should the manager panel auto-lock idle timeout be 5 minutes, or match the POS's existing inactivity policy?
3. Do managers need an audit list of manual/edited entries in the POS, or is Desk (`Employee Timeclock Tracking` list, filtered on `is_modified` / `manual_entry`) enough?
