"""Employee Timeclock Tracking export endpoint."""

import frappe

from excel_restaurant_pos.api.timeclock.helpers import get_request_data
from excel_restaurant_pos.shared.timeclock.export import (
	build_export_response,
	create_download_ticket,
	redeem_download_ticket,
)


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


@frappe.whitelist()
def timeclock_export_ticket():
	"""
	Mint a single use ticket so a browser can download the export directly.

	A cross origin SPA cannot put its `Authorization: Bearer` header on a
	`window.location` navigation, and fetching the file instead buffers the whole
	workbook in browser memory. Call this first, then point the browser at
	`api.timeclock.download?ticket=...`: the file streams straight to disk.

	Request: same `filters` / `columns` / `filename` as `api.timeclock.export`.
	The filters are frozen into the ticket, so redeeming it cannot widen the
	export.

	Response: { ticket, expires_in, filename }. The ticket is valid for one
	download and expires after two minutes.
	"""
	data = get_request_data()

	return create_download_ticket(
		raw_filters=data.get("filters"),
		raw_columns=data.get("columns") or data.get("fields"),
		filename=data.get("filename"),
	)


@frappe.whitelist(allow_guest=True)
def timeclock_export_download():
	"""
	Redeem a ticket from `api.timeclock.export_ticket` and stream the XLSX.

	Guest reachable by necessity -- a browser navigation carries no bearer token
	-- but it does nothing without a valid ticket, and the export then runs as
	the user who minted it, with that user's permissions.
	"""
	ticket = frappe.form_dict.get("ticket") or get_request_data().get("ticket")

	return redeem_download_ticket(ticket)
