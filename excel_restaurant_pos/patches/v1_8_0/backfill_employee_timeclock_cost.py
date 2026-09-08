"""Seed ArcPOS Employee.timeclock_cost from the retired global ArcPOS Settings rate.

The hourly rate moved from ArcPOS Settings onto each employee. Frappe creates a
Currency column as `not null default 0`, so every employee that predates the
field lands on 0 rather than NULL -- and Frappe's mandatory check counts 0 as a
value, so nothing would ever prompt for it. Left alone, every shift worked by an
existing employee would silently cost nothing.

At the moment this runs, no employee can have chosen 0 deliberately (the field
did not exist), so 0 unambiguously means "never set" and is safe to overwrite
with the rate those employees were already being costed at.

A direct UPDATE rather than a save per employee: saving would run the PIN
validation, and one employee with a legacy PIN would abort the whole migration.

Registered under [post_model_sync]: it reads a column the DocType sync creates,
so it cannot run before that sync.
"""

import frappe
from frappe.utils import flt

EMPLOYEE_DOCTYPE = "ArcPOS Employee"


def execute():
	# `has_column` raises TableMissingError rather than returning False when the
	# table is absent, so the table has to be checked first -- and uncached,
	# because the DocType may have been created by the sync in this same
	# migrate, after the table list was cached.
	if not frappe.db.table_exists(EMPLOYEE_DOCTYPE, cached=False):
		return

	if not frappe.db.has_column(EMPLOYEE_DOCTYPE, "timeclock_cost"):
		return

	# The deprecated single value, read directly. It is hidden and read only now
	# and nothing else in the app still looks at it.
	global_rate = flt(frappe.db.get_single_value("ArcPOS Settings", "timeclock_cost"))
	if not global_rate:
		# Nothing to copy. The employees stay at 0, which is what they were
		# already being costed at, and a manager can set real rates in the Desk.
		print("No global Timeclock Cost (Hourly) to seed from; ArcPOS Employee rates left at 0")
		return

	employees = frappe.get_all(EMPLOYEE_DOCTYPE, filters={"timeclock_cost": 0}, pluck="name")
	if not employees:
		return

	frappe.db.set_value(
		EMPLOYEE_DOCTYPE,
		{"name": ("in", employees)},
		"timeclock_cost",
		global_rate,
		update_modified=False,
	)
	frappe.db.commit()

	print(
		f"Seeded Timeclock Cost (Hourly) = {global_rate} on {len(employees)} ArcPOS Employee record(s)"
	)
