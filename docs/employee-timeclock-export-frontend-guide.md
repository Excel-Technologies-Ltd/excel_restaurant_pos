# Employee TimeTracking — Frontend Integration Guide

How the POS SPA renders the Employee TimeTracking report and exports it **without
anyone being logged into Frappe Desk**.

**Audience:** frontend developers on the POS SPA (`pos-order.aninda.me`).
**Backend reference:** [`employee-timeclock-api.md`](./employee-timeclock-api.md).

---

## 1. The one thing to understand first

The backend has **two independent ways in**, and they are not interchangeable:

| | Frappe Desk session | ArcPOS bearer token |
|---|---|---|
| Carried by | `sid` cookie, same origin | `Authorization: Bearer <jwt>` header |
| Set up by | logging into `/app` | `POST /api/method/excel_restaurant_pos.api.auth.login.login` |
| Works cross-origin | no | yes |
| Survives a `window.location` navigation | yes (cookie is sent) | **no** (you cannot put a header on a navigation) |

The SPA only ever has the **bearer token**. So:

- Every `fetch` you make must carry `Authorization: Bearer <accessToken>`.
- `window.location = ".../api/method/api.timeclock.export"` **cannot work** — a
  browser navigation carries no header, so it arrives as `Guest` and is refused.
  If your export is a plain link or a `window.location`, that is the bug.

Everything below is built around that one constraint.

---

## 2. Prerequisites

**Permissions.** Export requires the `export` permission on *Employee Timeclock
Tracking*. Viewing the report requires `report`.

| Role | View report | Export |
|------|-------------|--------|
| System Manager | yes | yes |
| ArcPOS Manager | yes | yes |
| Restaurant Manager | yes | **no** |

The user behind the token needs one of the first two to see a download button.
Hide the button rather than letting it 403 — see §6.

**CORS.** The API site's `site_config.json` must allow the SPA origin, or the
browser blocks the response before your code runs:

```json
{
  "allow_cors": "https://pos-order.aninda.me"
}
```

---

## 3. Rendering the report

`api.reports.employee_timeclock_summary` — `GET` or `POST`.

| Argument | Notes |
|----------|-------|
| `start_date`, `end_date` | `YYYY-MM-DD`. Both optional; defaults to today. |
| `employee_id` | An ArcPOS Employee `name` (the autoincrement id, e.g. `"7"`). Omit for every employee. |
| `page`, `page_size` | Paginates the **day columns**, not the employees. Default 20, max 200. |

```ts
const API = import.meta.env.VITE_API_BASE_URL;

export async function fetchTimeclockSummary(params: {
  startDate: string;
  endDate: string;
  employeeId?: string;
  page?: number;
  pageSize?: number;
}) {
  const query = new URLSearchParams({
    start_date: params.startDate,
    end_date: params.endDate,
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 20),
  });
  if (params.employeeId) query.set("employee_id", params.employeeId);

  const res = await fetch(
    `${API}/api/method/api.reports.employee_timeclock_summary?${query}`,
    { headers: { Authorization: `Bearer ${getAccessToken()}` } },
  );
  if (!res.ok) throw await toApiError(res);

  // Frappe wraps every whitelisted return value in `message`.
  return (await res.json()).message;
}
```

Response shape:

```jsonc
{
  "date_range": { "start_date": "2026-09-01", "end_date": "2026-09-30", "total_days": 30 },
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 2, "hasNextPage": true, "hasPreviousPage": false },
  "date_summary": [
    {
      "date": "2026-09-01",
      "day": "Tue, Sep 01",       // preformatted, ready to render
      "total_hours": 62.5,
      "total_cost": 145.0,        // see the warning below
      "total_payment": 1250.0,
      "employee_count": 8
    }
  ],
  "employees": [
    {
      "employee_id": 7,           // note: employee_id, not employee
      "employee_name": "Aisha Rahman",
      "role": "Waiter",
      "total_hours": 168.5,
      "total_cost": 400.0,        // see the warning below
      "total_payment": 3370.0,
      "working_days": 20,
      "avg_daily_hours": 8.43,
      "daily_slots": [
        {
          "date": "2026-09-01",
          "day": "Tue, Sep 01",
          "check_in": "9:00 AM",  // preformatted string, "" when absent
          "check_out": "5:30 PM",
          "hours_worked": 8.5,
          "cost": 20.0,           // the hourly rate for that day
          "payment": 170.0,
          "remarks": ""           // shift note, "" when there is none
        }
      ]
    }
  ]
}
```

Three things to get right when you bind this:

- **The money column is `total_payment`, not `total_cost`.** `total_cost` is
  `SUM(timeclock_cost)` — a sum of *hourly rates* across days, which is not a
  currency figure and means nothing on its own. Rendering it as money would
  show wrong numbers to whoever signs off payroll. Inside `daily_slots`, `cost`
  is likewise that day's hourly rate and `payment` is the money.
- `date`/`day` and `check_in`/`check_out` come **preformatted** from the
  database. Do not re-parse `check_in` as a timestamp — it is a display string
  like `"9:00 AM"`, and `""` when the employee never clocked that day.
- `date_summary`, `employees` and `daily_slots` are always arrays. The backend
  normalises SQL `NULL` to `[]`, so you can map over them without guarding.
- `remarks` is the free text shift note, `""` when there is none (the procedure
  coalesces `NULL`). It is filterable and exportable like any other column.

`page`/`page_size` paginate the **day columns**, not the employees: every
employee comes back on every page, each carrying only the `daily_slots` for the
requested window of dates. Drive horizontal scrolling of the date axis with it,
not a list of people.

---

## 4. Exporting — pick one of two paths

Both authenticate with the same bearer token and neither needs a Frappe session.

### Option A — `fetch` + blob (use this by default)

The whole download stays on your own origin. The backend URL never appears in
the address bar or the browser's download list, and you keep control of the
loading state.

```ts
export async function downloadTimeclockExport(filters: unknown[]) {
  const res = await fetch(`${API}/api/method/api.timeclock.export`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${getAccessToken()}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ filters }),
  });
  if (!res.ok) throw await toApiError(res);

  // Readable cross-origin: the response sets Access-Control-Expose-Headers.
  const rows = Number(res.headers.get("X-Row-Count") ?? 0);
  const filename =
    filenameFromDisposition(res.headers.get("Content-Disposition")) ??
    "employee-timeclock.xlsx";

  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href, download: filename });
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);

  return { rows, filename };
}

function filenameFromDisposition(header: string | null) {
  if (!header) return null;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match ? decodeURIComponent(match[1]) : null;
}
```

**Trade-off:** the entire workbook is held in the tab until the blob is revoked.
Fine for a month of shifts; not for a year of an entire chain.

### Option B — one-time ticket + navigation (large exports)

The browser streams straight to disk with a native progress bar, and nothing is
buffered in JS. The cost is that the user briefly navigates to the backend
origin, so that URL is visible to them.

```ts
export async function downloadTimeclockExportStreaming(filters: unknown[]) {
  // 1. Mint the ticket with the bearer token you already hold.
  const res = await fetch(`${API}/api/method/api.timeclock.export_ticket`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${getAccessToken()}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ filters }),
  });
  if (!res.ok) throw await toApiError(res);
  const { ticket } = (await res.json()).message;

  // 2. Hand the browser the download. No header needed — the ticket carries
  //    the identity. Mint it at the moment of the click: it lasts 2 minutes.
  window.location.href =
    `${API}/api/method/api.timeclock.download?ticket=${encodeURIComponent(ticket)}`;
}
```

The ticket is **single use**, expires after **120 seconds**, and freezes the
filters, columns, filename and minting user at the moment it is created — so
redeeming it cannot widen the export or run as anyone else. Treat it as a
password with a two minute life: mint it on the click, never log it, never put
it in application state that gets persisted.

### Which one?

| Situation | Use |
|-----------|-----|
| Normal date-ranged export from the report screen | **A** |
| You need an in-app progress indicator | **A** |
| Backend URL must never be visible to the user | **A** |
| Tens of thousands of rows | **B** |

---

## 5. Filters and columns

Both export endpoints take the same three optional arguments. Omit all of them
and you export the entire DocType (subject to the row cap).

**`filters`** — Desk-style `[field, operator, value]` triples, or a plain object
for equality:

```ts
[
  ["business_date", "between", ["2026-09-01", "2026-09-30"]],
  ["employee", "=", "7"],
]

// equivalent shorthand for equality only
{ employee: "7" }
```

Allowed operators: `=` `!=` `>` `<` `>=` `<=` `like` `not like` `in` `not in`
`between` `is`. Anything else is rejected rather than passed to the query
builder. Field names are validated against the DocType, so a typo returns a
`ValidationError` naming the field rather than exporting the wrong thing.

**`columns`** — fieldnames to write. Defaults to the full record:

`name`, `employee`, `employee_name`, `business_date`, `first_check_in`,
`last_check_out`, `total_paid_hours`, `timeclock_cost`, `total_payment`,
`manual_entry`, `is_modified`, `modified_by_manager`, `remarks`

Layout fields (section breaks, column breaks) and `pin` are not selectable.

**`filename`** — overrides the generated `employee-timeclock-<timestamp>.xlsx`.

> Always send a `business_date` range from the report screen. It is what the
> user is looking at, and it keeps the export well under the row cap.

---

## 6. Errors

Frappe returns a non-2xx status with the message in `_server_messages` (a
JSON-encoded array of JSON strings — yes, doubly encoded) and the exception class
in `exception`. One helper handles every endpoint here:

```ts
export async function toApiError(res: Response) {
  let message = res.statusText;
  try {
    const body = await res.json();
    const serverMessages = JSON.parse(body._server_messages ?? "[]");
    if (serverMessages.length) {
      message = JSON.parse(serverMessages[0]).message ?? message;
    } else if (body.exception) {
      message = String(body.exception);
    }
  } catch {
    // Non-JSON body (a proxy error page, say) — keep the status text.
  }
  return new Error(message);
}
```

| Status / message | Cause | What to do |
|---|---|---|
| `Not permitted` (403) | Token user lacks `export`, **or** a navigation arrived without a header | Hide the button for roles without export; if it is a navigation, switch to §4 |
| `Too many exports. Please try again in a minute.` | 6 exports per user per minute | Disable the button for 60s and say why |
| `This export would exceed 100000 rows…` | Unfiltered export of a large table | Force a date range |
| `This download link has expired…` | Ticket older than 120s, or already redeemed | Mint a fresh one on the next click — never reuse |
| `… is not a valid Employee Timeclock Tracking field` | Bad `filters`/`columns` fieldname | Fix the client payload |
| CORS error in the console, no response | `allow_cors` missing the SPA origin | §2 |

---

## 7. Limits

| Limit | Value |
|-------|-------|
| Exports per user | 6 per minute |
| Rows per export | 100,000 |
| Ticket lifetime | 120 seconds, single use |
| Report page size | 20 default, 200 max |

Every export is written to **Access Log** with the acting user, filters and row
count. This is payroll data — assume it is audited, because it is.

---

## 8. Testing checklist

- [ ] Export from a browser with **no Frappe session at all** — use a private
      window. An ordinary tab may still hold the Desk cookie and hide exactly
      the class of bug this flow exists to avoid.
- [ ] Export while also logged into Desk in another tab — must still work, and
      must not break that Desk session on the next request.
- [ ] Export as an ArcPOS Manager (allowed) and a Restaurant Manager (refused,
      button hidden).
- [ ] An expired token → your refresh flow runs, not a silent empty file.
- [ ] Redeem the same ticket twice → second attempt shows the expiry message.
- [ ] Let a ticket sit for 3 minutes before redeeming → expiry message.
- [ ] A date range with no records → an empty workbook with a header row, not
      an error.
- [ ] Fire the export button twice quickly → no double download, no torn file.
- [ ] Filename and row count in the UI match the file that lands on disk.
