"""Employee timeclock summary report, served by the GetEmployeeTimeclockSummary procedure."""

import json

import pymysql.cursors

import frappe
from frappe import _
from frappe.utils import cint, getdate

PROCEDURE = "GetEmployeeTimeclockSummary"
TRACKING_DOCTYPE = "Employee Timeclock Tracking"

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


def _date_arg(value):
	"""Dates are validated here rather than passed through to the procedure."""
	if value in (None, "", "null"):
		return None
	return getdate(value)


def _connection_settings():
	settings = dict(frappe.db.get_connection_settings())
	# Absent when the site logs in as root; the procedure lives in the site db.
	settings.setdefault("database", frappe.conf.db_name)
	settings["cursorclass"] = pymysql.cursors.DictCursor
	return settings


def _call_procedure(args):
	"""Run the procedure on its own connection.

	A CALL leaves extra result sets on the wire, and draining them on frappe's
	shared connection corrupts the packet sequence for the rest of the request --
	the same reason api.reports.sales_by_service opens its own connection.
	"""
	connection = pymysql.connect(**_connection_settings())
	try:
		with connection.cursor() as cursor:
			cursor.callproc(PROCEDURE, args)
			rows = cursor.fetchall()
			while cursor.nextset():
				pass
		return rows
	finally:
		connection.close()


def _empty_result(start_date, end_date, page, page_size):
	return {
		"date_range": {
			"start_date": str(start_date) if start_date else None,
			"end_date": str(end_date) if end_date else None,
			"total_days": 0,
		},
		"pagination": {
			"page": page,
			"pageSize": page_size,
			"totalPages": 0,
			"hasNextPage": False,
			"hasPreviousPage": page > 1,
		},
		"date_summary": [],
		"employees": [],
	}


@frappe.whitelist()
def get_employee_timeclock_summary(
	start_date=None, end_date=None, employee_id=None, page=1, page_size=None
):
	"""
	Timeclock hours and payroll totals per employee, with a per-day breakdown.

	Requires the Report permission on Employee Timeclock Tracking, the same
	permission that gates the XLSX export.

	Request
	-------
	start_date, end_date (optional): defaults to today inside the procedure
	employee_id (optional): an ArcPOS Employee name; blank means every employee
	page, page_size (optional): paginate the day columns, not the employees

	Response
	--------
	{ date_range, pagination, date_summary[], employees[] } where each employee
	carries totals plus `daily_slots` for the requested page of days.
	"""
	frappe.has_permission(TRACKING_DOCTYPE, ptype="report", throw=True)

	start_date = _date_arg(start_date)
	end_date = _date_arg(end_date)
	if start_date and end_date and end_date < start_date:
		frappe.throw(_("End Date cannot be earlier than Start Date"), frappe.ValidationError)

	page = max(cint(page) or 1, 1)
	page_size = min(cint(page_size) or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)

	employee_id = (str(employee_id).strip() if employee_id else "") or None

	rows = _call_procedure((start_date, end_date, employee_id, page, page_size))

	payload = (rows[0] or {}).get("json_result") if rows else None
	if not payload:
		# No timeclock rows in range: the procedure returns SQL NULL, not JSON.
		return _empty_result(start_date, end_date, page, page_size)

	if isinstance(payload, (bytes, bytearray)):
		payload = payload.decode("utf-8")

	result = json.loads(payload) if isinstance(payload, str) else payload

	# JSON_ARRAYAGG yields NULL rather than [] when a section has no rows.
	for key in ("date_summary", "employees"):
		if result.get(key) is None:
			result[key] = []
	for employee in result["employees"]:
		if employee.get("daily_slots") is None:
			employee["daily_slots"] = []

	return result
