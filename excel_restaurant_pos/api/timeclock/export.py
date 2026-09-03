"""Employee Timeclock Tracking export endpoint."""

import frappe

from excel_restaurant_pos.api.timeclock.helpers import get_request_data
from excel_restaurant_pos.shared.timeclock.export import build_export_response


@frappe.whitelist()
def timeclock_export():
	"""
	Download Employee Timeclock Tracking records as an XLSX file.

	Requires the Export permission on Employee Timeclock Tracking, and rows are
	read with the caller's own permissions -- an unfiltered request exports only
	what that user is allowed to see.

	Request
	-------
	filters (optional): Desk style filters, e.g.
	    [["business_date", "between", ["2026-09-01", "2026-09-30"]],
	     ["employee", "=", "6"]]
	    Omit to export the whole doctype.
	columns (optional): fieldnames to write, defaults to the full record.
	filename (optional): overrides the generated file name.

	Response
	--------
	A streamed XLSX attachment. The row count is also returned in the
	`X-Row-Count` header.
	"""
	data = get_request_data()

	return build_export_response(
		raw_filters=data.get("filters"),
		raw_columns=data.get("columns") or data.get("fields"),
		filename=data.get("filename"),
	)
