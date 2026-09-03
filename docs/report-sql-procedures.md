# Stored procedures in `report_sql/`

SQL-backed reports live as `.sql` files under
`excel_restaurant_pos/report_sql/`. Adding a report means adding a file — no
patch module per procedure.

## Adding or changing a procedure

1. Drop a `.sql` file in `excel_restaurant_pos/report_sql/`.
2. `bench --site <site> migrate`.

The `after_migrate` hook (`hooks.py`) runs
`excel_restaurant_pos.shared.sql_procedures.sync.sync_sql_objects`, which
installs **every** file in the folder on **every** migrate. `DROP … IF EXISTS`
followed by `CREATE` is idempotent and takes milliseconds, so nothing tracks
which version was installed last: the file on disk is always what the database
gets. Editing an existing file and migrating is all a change needs.

`patches.txt` also carries
`excel_restaurant_pos.patches.v1_7_0.sync_report_sql_objects`. That entry exists
so the procedures land on the migrate that introduces the folder, and so a forced
re-install has an entry point:

```bash
bench --site <site> execute \
  excel_restaurant_pos.patches.v1_7_0.sync_report_sql_objects.execute
```

A file that fails to install **aborts the migrate**, naming the file in the
error. That is deliberate: a silently skipped procedure means a report that is
broken at runtime instead of at deploy time.

## Writing a file

`DELIMITER` is a mysql *client* directive, not SQL. The installer interprets it
and never sends it to the server, so procedure bodies keep their internal `;`.
Two rules keep a file parseable:

* **A statement terminator ends its line.** The splitter treats a line ending in
  the active delimiter as the end of a statement, which is what keeps a `;`
  inside `DATE_FORMAT(d, '%a, %b %d')` from splitting anything.
* **Put `DROP PROCEDURE` above `DELIMITER //`.** While `//` is the active
  delimiter a trailing `;` no longer terminates a statement, so a `DROP …;`
  written below the directive gets glued onto the `CREATE PROCEDURE` that
  follows and the whole file fails as one malformed statement.

```sql
DROP PROCEDURE IF EXISTS `MyReport`;

DELIMITER //

CREATE PROCEDURE `MyReport`(IN p_from DATE)
BEGIN
    SELECT 1;
END //

DELIMITER ;
```

## Calling a procedure from an endpoint

Open a **dedicated connection**. A `CALL` leaves extra result sets on the wire,
and draining them on frappe's shared connection corrupts the packet sequence for
the rest of the request. `api/report/get_employee_timeclock_summary.py` and
`api/report/get_sales_by_service_type.py` both follow this shape.

---

## `api.reports.employee_timeclock_summary`

Wraps `GetEmployeeTimeclockSummary`. Requires the **Report** permission on
Employee Timeclock Tracking — System Manager, ArcPOS Manager and Restaurant
Manager by the DocType's own permissions.

The report is read only, so it is a `GET` — linkable, bookmarkable, and no body
to build:

```http
GET /api/method/api.reports.employee_timeclock_summary
    ?start_date=2026-09-01&end_date=2026-09-30&employee_id=6&page=1&page_size=20
```

```js
const q = new URLSearchParams({
  start_date: "2026-09-01",
  end_date: "2026-09-30",
  employee_id: "6",
  page: 1,
  page_size: 20,
});
const res = await fetch(`${API}/api/method/api.reports.employee_timeclock_summary?${q}`, {
  headers: { Authorization: `Bearer ${accessToken}` },
});
const report = (await res.json()).message;
```

`POST` with a JSON body is accepted as well, for callers that post everything.

| Argument | Default | Notes |
|----------|---------|-------|
| `start_date`, `end_date` | today | Rejected if the end precedes the start |
| `employee_id` | every employee | An ArcPOS Employee name; blank is treated as unset |
| `page` | 1 | Floored at 1 |
| `page_size` | 20 | Capped at 200. **Pages the day columns, not the employees** |

Response:

```jsonc
{
  "date_range":   { "start_date": "2026-09-01", "end_date": "2026-09-30", "total_days": 30 },
  "pagination":   { "page": 1, "pageSize": 20, "totalPages": 2,
                    "hasNextPage": true, "hasPreviousPage": false },
  "date_summary": [ { "date", "day", "total_hours", "total_cost",
                      "total_payment", "employee_count" } ],
  "employees":    [ { "employee_id", "employee_name", "role",
                      "total_hours", "total_cost", "total_payment",
                      "working_days", "avg_daily_hours",
                      "daily_slots": [ { "date", "day", "check_in", "check_out",
                                         "hours_worked", "cost", "payment" } ] } ]
}
```

`date_summary`, `employees` and `daily_slots` are always arrays. The procedure
returns SQL `NULL` from `JSON_ARRAYAGG` when a section is empty, and a range with
no timeclock rows at all returns `NULL` instead of a JSON document; the endpoint
normalises both to the shape above so the frontend never has to null-check.
