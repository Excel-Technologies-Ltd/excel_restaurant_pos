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

---

## 5. Errors

| Situation | Exception | HTTP |
|-----------|-----------|------|
| PIN not 6 digits | `ValidationError` | 417 |
| Unknown or inactive PIN | `AuthenticationError` | 401 |
| More than 10 failed PINs in 5 minutes (per user + IP) | `AuthenticationError` | 401 |
| Non-manager PIN on a manager route | `PermissionError` | 403 |
| Record missing / already exists / bad timestamps | `ValidationError` family | 417 |

Read the message from `_server_messages` or `exception` as with the other ArcPOS APIs.
