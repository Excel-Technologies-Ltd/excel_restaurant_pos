"""Give existing sites the default hourly order limit.

A new field on a Single has no stored value on sites that already exist, and an
empty Int reads as 0 -- which here means "no limit". Only an unset value is
filled; a limit someone already chose is left alone.
"""

import frappe

from excel_restaurant_pos.shared.sales_invoice.order_limit import (
	DEFAULT_LIMIT,
	SETTINGS_DOCTYPE,
	SETTINGS_FIELD,
)


def execute():
	stored = frappe.db.sql(
		"select value from `tabSingles` where doctype = %s and field = %s",
		(SETTINGS_DOCTYPE, SETTINGS_FIELD),
	)
	if stored and stored[0][0] not in (None, ""):
		return

	frappe.db.set_single_value(SETTINGS_DOCTYPE, SETTINGS_FIELD, DEFAULT_LIMIT)
