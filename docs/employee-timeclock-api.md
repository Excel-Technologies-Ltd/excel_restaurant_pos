# Employee Timeclock — Backend & API Guide

Backend for the POS **Employee Timeclock** menu: PIN numpad check in / check out, and the manager override panels.

**Audience:** POS (React) developers and anyone calling the whitelisted `api.timeclock.*` routes.
**Backend contract:** every call is identified by a 6-digit employee PIN — the POS never sends an employee id for check in / check out.

---

## 1. Concepts

| Term | Meaning |
|------|---------|
| **Business day** | Runs from **04:01 AM (day T) to 04:00 AM (day T+1)**. Any timestamp at or before 04:00 AM belongs to the previous business date. |
| **Business date** | The `Date` a timeclock record is filed under. One record per employee per business date. |
| **PIN** | 6 digits, hashed with the site encryption key. Never stored or returned in plain text. Two *active* employees cannot share a PIN. |
| **Open record** | A record whose `last_check_out` is empty. While an **earlier** business date is open, the employee cannot start a new entry — a manager must fix it first. |

---

## 2. DocTypes

### ArcPOS Employee

| Field | Type | Notes |
|-------|------|-------|
| `name` | Autoincrement | The `employee_id`. Link target of the tracking record. |
| `employee_name` | Data | Required. |
| `role` | Select | `Manager`, `Waiter`, `Barista`, `Cashier`. |
| `new_pin` | Data | Write-only input: enter 6 digits, hashed on save, then cleared. |
| `pin` | Data (read only) | Stored hash. Used to look the employee up from the numpad. |
| `is_active` | Check | Default `1`. Inactive employees cannot authenticate. |

The hash is keyed with the site `encryption_key`, so PINs must be re-issued if that key is ever rotated.

### Employee Timeclock Tracking

| Field | Type | Notes |
|-------|------|-------|
| `employee` | Link → ArcPOS Employee | Set once. |
| `business_date` | Date | Set once. Naming is `ETT-{business_date}-{employee}`, so one record per employee per business date is guaranteed at DB level. |
| `first_check_in` | Datetime | Written by the first check in of the business day. |
| `last_check_out` | Datetime | Replaced by every check out before the 04:00 AM cutoff. |
| `total_paid_hours` | Float (2 dp), read only | `last_check_out - first_check_in`, in hours. `0` while incomplete. |
| `timeclock_cost` | Currency | Copied from **ArcPOS Settings → Timeclock Cost (Hourly)** when the record is created. |
| `total_payment` | Currency, read only | `total_paid_hours × timeclock_cost`. |
| `manual_entry` | Check, read only | Manager created the record for a date the employee never clocked. |
| `is_modified` | Check, read only | Manager edited the timestamps of an existing record. |
| `modified_by_manager` | Link → ArcPOS Employee, read only | The manager who edited or created it. Named `modified_by_manager` because `modified_by` is a reserved Frappe column. |

### ArcPOS Settings

New field `timeclock_cost` (Currency, *Employee Timeclock* section) — the hourly rate.

---

## 3. Setup

```bash
bench --site <site> migrate
```

Then: set **ArcPOS Settings → Timeclock Cost (Hourly)**, and create **ArcPOS Employee** records with a role and a 6-digit PIN.

---

## 4. API

All routes are whitelisted overrides, `POST`, and require an authenticated POS session (same auth as the other `api.*` routes). Frappe wraps every response in `message`.

```ts
const { call } = useFrappePostCall("api.timeclock.authenticate");
const res = await call({ pin: "123456" });
const payload = res.message;
```

### `api.timeclock.authenticate` — numpad PIN → button state

Request: `{ "pin": "123456" }`

```json
{
  "employee": 7,
  "employee_name": "Aisha Rahman",
  "role": "Waiter",
  "is_manager": false,
  "business_date": "2026-09-01",
  "action": "check_in",
  "can_check_in": true,
  "can_check_out": false,
  "message": null,
  "open_record": null,
  "record": null
}
```

`action` drives the modal:

| `action` | Meaning | UI |
|----------|---------|----|
| `check_in` | No check in yet for the current business date | Enable **Check-In** |
| `check_out` | Already checked in | Enable **Check-Out** (repeatable — each click replaces `last_check_out`) |
| `blocked` | An earlier business date has no check out | Disable both, show `message`; `open_record` names the offending date |

### `api.timeclock.check_in`

Request: `{ "pin": "123456" }` → `{ "action": "check_out", "record": { … } }`

Errors: already checked in for the business date; an earlier business date is still open.

### `api.timeclock.check_out`

Request: `{ "pin": "123456" }` → `{ "action": "check_out", "record": { … } }`

Every call replaces `last_check_out` with the current time and recalculates `total_paid_hours` / `total_payment`.

Errors: no check in exists for the current business date.

### `api.timeclock.manager_authenticate` — unlock "Timeclock Edit" / "Add"

Request: `{ "manager_pin": "654321" }`

```json
{
  "manager": { "employee": 2, "employee_name": "Karim", "role": "Manager", "is_manager": true },
  "employees": [{ "employee": 7, "employee_name": "Aisha Rahman", "role": "Waiter", "is_active": 1 }]
}
```

A PIN whose role is not `Manager` returns `PermissionError`.

### `api.timeclock.employees`

Request: `{ "manager_pin": "654321", "include_inactive": 0 }` → `{ "employees": [ … ] }`

### `api.timeclock.get_record` — load the record into the edit form

Request: `{ "manager_pin": "654321", "employee": 7, "business_date": "2026-09-01" }`

Returns `{ "employee": 7, …, "business_date": "2026-09-01", "record": { … } | null }`.

### `api.timeclock.update_record` — manager edit

Request:

```json
{
  "manager_pin": "654321",
  "employee": 7,
  "business_date": "2026-09-01",
  "first_check_in": "2026-09-01 09:05:00",
  "last_check_out": "2026-09-01 17:40:00"
}
```

Omit a timestamp to leave it unchanged; send `""` to clear it. Saving sets `is_modified = 1`, stores the manager in `modified_by_manager`, and recalculates `total_paid_hours` / `total_payment`.

Errors: no record for that employee/date; `last_check_out` earlier than `first_check_in`.

### `api.timeclock.add_entry` — manager manual entry

Request: same shape as `update_record`; `first_check_in` is required, `last_check_out` optional.

Creates the record with `manual_entry = 1` and `modified_by_manager` set. `timeclock_cost` is taken from ArcPOS Settings at creation, and `total_working_hours` comes back as `total_paid_hours`.

Errors: a record already exists for that employee/date (edit it instead).

### `api.timeclock.export` — XLSX download

Streams Employee Timeclock Tracking rows as an `.xlsx` attachment. Unlike every
other route here this one is **session authenticated, not PIN authenticated**:
the caller must be logged in and hold the **Export** permission on Employee
Timeclock Tracking. By the DocType's own permissions that means System Manager
and ArcPOS Manager; Restaurant Manager can read records in the POS but cannot
export them.

Request (all optional — omit everything to export the whole DocType):

| Argument | Shape | Notes |
|----------|-------|-------|
| `filters` | Desk filters, JSON | `[["business_date","between",["2026-09-01","2026-09-30"]],["employee","=","6"]]`, or a plain object `{"employee": "6"}` |
| `columns` | list of fieldnames | Defaults to the full record |
| `filename` | string | Defaults to `employee-timeclock-<timestamp>.xlsx` |

```js
// the browser handles the download; do not fetch() this into memory
window.location = "/api/method/api.timeclock.export"
  + "?filters=" + encodeURIComponent(JSON.stringify([
      ["business_date", "between", ["2026-09-01", "2026-09-30"]],
    ]));
```

Response headers:

| Header | Value |
|--------|-------|
| `Content-Type` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| `Content-Disposition` | `attachment; filename=employee-timeclock-….xlsx` |
| `Content-Length` | exact size, so the browser can show progress |
| `X-Row-Count` | rows written, excluding the header |
| `Cache-Control` | `no-store, no-cache, must-revalidate, private` |

How it stays safe and flat in memory:

- Rows are read with **the caller's own permissions**, so an unfiltered export
  returns only what that user may already see.
- Filter fieldnames are checked against the DocType and the operator against a
  fixed list, so nothing arbitrary reaches the query builder.
- Rows are pulled in batches of 500, **keyset paged on `name`** rather than by
  offset, so a check-in recorded mid-export cannot skip or duplicate a row.
- The workbook is written in openpyxl's write-only mode, so memory does not grow
  with the row count.
- The finished file goes to a temp path, is streamed in 64 KB chunks and is
  deleted as the stream drains. Nothing is ever written to `/files`, so there is
  no guessable URL for wage data.
- Six exports per user per minute; beyond that the request is rejected.
- Over 100,000 rows the export is refused with a message asking for filters.
- Every export is recorded in **Access Log** with the filters and row count.

### `api.timeclock.export_ticket` + `api.timeclock.download` — cross-origin downloads

The SPA at `pos-order.aninda.me` authenticates with `Authorization: Bearer <jwt>`
(`excel_restaurant_pos.auth.validate`). A browser navigation cannot carry that
header, so `window.location = ".../api.timeclock.export"` arrives as **Guest**
and is refused. Fetching the file instead works, but `response.blob()` buffers
the whole workbook in browser memory, which throws away the streaming.

Two steps instead:

```js
// 1. mint a ticket with the bearer token you already have
const res = await fetch(`${API}/api/method/api.timeclock.export_ticket`, {
  method: "POST",
  headers: { "Authorization": `Bearer ${accessToken}`, "Content-Type": "application/json" },
  body: JSON.stringify({
    filters: [["business_date", "between", ["2026-09-01", "2026-09-30"]]],
  }),
});
const { ticket } = (await res.json()).message;

// 2. let the browser download it -- streams to disk, native progress, no JS memory
window.location = `${API}/api/method/api.timeclock.download?ticket=${encodeURIComponent(ticket)}`;
```

The ticket is random (32 bytes), **single use**, expires after **two minutes**,
and carries the filters, columns, filename and minting user. Redeeming it runs
the export as that user with that user's permissions, so a ticket cannot be
replayed, widened, or used to export someone else's view. `api.timeclock.download`
is the only guest-reachable route here and does nothing at all without a valid
ticket.

Because the ticket travels in the query string, the response sets
`Referrer-Policy: no-referrer`. Treat the ticket as a password with a two minute
life: mint it at the moment of the click, never log it.

**If you would rather stay on `fetch`** (an in-app progress bar, no navigation),
call `api.timeclock.export` directly with the bearer header and read the blob.
The response sets `Access-Control-Expose-Headers`, so `Content-Disposition`,
`Content-Length` and `X-Row-Count` are readable cross-origin — Frappe's own CORS
handling sets `Allow-Origin` but never `Expose-Headers`. The server still streams
and stays flat in memory; only the browser buffers.

**Site config prerequisite.** Cross-origin calls need the API site's
`site_config.json` to allow the SPA's origin, otherwise the browser blocks the
response before your code sees it:

```json
{ "allow_cors": ["https://pos-order.aninda.me"] }
```

---

## 5. Errors

| Situation | Exception | HTTP |
|-----------|-----------|------|
| PIN not 6 digits | `ValidationError` | 417 |
| Unknown or inactive PIN | `AuthenticationError` | 401 |
| More than 10 failed PINs in 5 minutes (per user + IP) | `AuthenticationError` | 401 |
| Non-manager PIN on a manager route | `PermissionError` | 403 |
| Record missing / already exists / bad timestamps | `ValidationError` family | 417 |
| Export without the Export permission | `PermissionError` | 403 |
| Export: unknown filter field, bad operator, over the row cap, or throttled | `ValidationError` | 417 |
| Download ticket missing, forged, expired, or already used | `AuthenticationError` | 401 |

Read the message from `_server_messages` or `exception` as with the other ArcPOS APIs.
