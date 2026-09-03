"""Streaming XLSX export for Employee Timeclock Tracking.

The workbook is written in openpyxl's write only mode while rows are pulled from
the database in keyset paged batches, so memory stays flat whether the caller
exports one shift or the whole table. The finished file is then streamed off
disk in chunks and deleted, so nothing is ever published to /files where the URL
could be guessed.
"""

from __future__ import annotations

import datetime
import os
import tempfile

import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

from excel_restaurant_pos.shared.timeclock.services import TRACKING_DOCTYPE

XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_NAME = "Employee Timeclock"

# Without an explicit format Excel renders a Date cell as a midnight timestamp.
NUMBER_FORMATS = {
	"Date": "yyyy-mm-dd",
	"Datetime": "yyyy-mm-dd hh:mm:ss",
	"Time": "hh:mm:ss",
}

# Rows fetched per database round trip.
BATCH_SIZE = 500

# Bytes handed to the WSGI server per chunk while streaming the finished file.
STREAM_CHUNK_SIZE = 64 * 1024

# A guard against an accidental unfiltered export of a table that has been
# growing for years, not a policy limit -- the error tells the caller to filter.
MAX_ROWS = 100_000

# Exports are expensive; one user should not be able to queue them in a loop.
EXPORT_RATE_LIMIT = 6
EXPORT_RATE_WINDOW = 60

DEFAULT_COLUMNS = (
	"name",
	"employee",
	"employee_name",
	"business_date",
	"first_check_in",
	"last_check_out",
	"total_paid_hours",
	"timeclock_cost",
	"total_payment",
	"manual_entry",
	"is_modified",
	"modified_by_manager",
)

STANDARD_FIELDS = ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx")

# Filter operators the export understands. Anything else is rejected rather than
# handed to the query builder.
ALLOWED_OPERATORS = (
	"=",
	"!=",
	">",
	"<",
	">=",
	"<=",
	"like",
	"not like",
	"in",
	"not in",
	"between",
	"is",
)


# ---------------------------------------------------------------------------
# Request argument validation
# ---------------------------------------------------------------------------


def _meta():
	return frappe.get_meta(TRACKING_DOCTYPE)


def permitted_fieldnames() -> set:
	"""Fieldnames the caller may select or filter on."""
	return set(STANDARD_FIELDS) | {
		df.fieldname for df in _meta().fields if df.fieldtype not in no_value_fields
	}


def _validate_fieldname(fieldname, permitted):
	if fieldname not in permitted:
		frappe.throw(
			_("{0} is not a valid {1} field").format(fieldname, _(TRACKING_DOCTYPE)),
			frappe.ValidationError,
		)


def parse_filters(raw_filters) -> list:
	"""Normalise caller supplied filters to a validated list of triples.

	Accepts the shapes the Desk sends: a JSON string, a dict, or a list of
	[fieldname, operator, value].
	"""
	if isinstance(raw_filters, str):
		raw_filters = raw_filters.strip()
		raw_filters = frappe.parse_json(raw_filters) if raw_filters else None

	if not raw_filters:
		return []

	if isinstance(raw_filters, dict):
		raw_filters = [[fieldname, "=", value] for fieldname, value in raw_filters.items()]

	permitted = permitted_fieldnames()
	filters = []
	for filter_row in raw_filters:
		if isinstance(filter_row, dict):
			filters.extend([fieldname, "=", value] for fieldname, value in filter_row.items())
			continue

		if not isinstance(filter_row, (list, tuple)) or len(filter_row) != 3:
			frappe.throw(
				_("Each filter must be [field, operator, value]"), frappe.ValidationError
			)
		filters.append(list(filter_row))

	for fieldname, operator, _value in filters:
		_validate_fieldname(fieldname, permitted)
		if str(operator).strip().lower() not in ALLOWED_OPERATORS:
			frappe.throw(
				_("Unsupported filter operator: {0}").format(operator), frappe.ValidationError
			)

	return filters


def resolve_columns(raw_columns=None) -> list:
	"""Columns to write, defaulting to the full timeclock record."""
	if isinstance(raw_columns, str):
		raw_columns = raw_columns.strip()
		raw_columns = frappe.parse_json(raw_columns) if raw_columns else None

	if not raw_columns:
		return list(DEFAULT_COLUMNS)

	if isinstance(raw_columns, str):
		raw_columns = [raw_columns]

	permitted = permitted_fieldnames()
	for fieldname in raw_columns:
		_validate_fieldname(fieldname, permitted)

	return list(raw_columns)


def column_labels(columns) -> list:
	"""Human readable header row."""
	labels = {df.fieldname: df.label for df in _meta().fields if df.label}
	return [_(labels.get(fieldname) or frappe.unscrub(fieldname)) for fieldname in columns]


# ---------------------------------------------------------------------------
# Row streaming
# ---------------------------------------------------------------------------


def _guard_export_rate():
	"""Throttle exports per user."""
	key = f"arcpos:timeclock_export:{frappe.session.user}"
	cache = frappe.cache()
	attempts = cint(cache.get_value(key))
	if attempts >= EXPORT_RATE_LIMIT:
		frappe.throw(
			_("Too many exports. Please try again in a minute."), frappe.ValidationError
		)
	cache.set_value(key, attempts + 1, expires_in_sec=EXPORT_RATE_WINDOW)


def iter_records(filters, columns, batch_size=None):
	"""Yield timeclock rows in batches, honouring the user's read permissions.

	Paged on `name` rather than with an offset: `name` is the primary key, so a
	record inserted mid-export can never cause a row to be skipped or repeated.
	"""
	batch_size = batch_size or BATCH_SIZE
	fields = list(dict.fromkeys(["name", *columns]))
	last_name = None
	exported = 0

	while True:
		page_filters = list(filters)
		if last_name is not None:
			page_filters.append(["name", ">", last_name])

		batch = frappe.get_list(
			TRACKING_DOCTYPE,
			filters=page_filters,
			fields=fields,
			order_by="name asc",
			limit_page_length=batch_size,
			ignore_permissions=False,
		)
		if not batch:
			return

		for row in batch:
			exported += 1
			if exported > MAX_ROWS:
				frappe.throw(
					_("This export would exceed {0} rows. Please narrow the filters.").format(
						MAX_ROWS
					),
					frappe.ValidationError,
				)
			yield row

		last_name = batch[-1]["name"]
		if len(batch) < batch_size:
			return


def _cell_value(value, fieldtype):
	"""Convert a stored value into something openpyxl can write natively."""
	if value is None or value == "":
		return None
	if fieldtype == "Check":
		return cint(value)
	if fieldtype in ("Currency", "Float", "Percent"):
		return flt(value)
	if fieldtype == "Int":
		return cint(value)
	if fieldtype == "Date":
		return getdate(value)
	if fieldtype == "Datetime":
		return get_datetime(value)
	if isinstance(value, (datetime.date, datetime.datetime)):
		return value
	return str(value)


def _build_cell(sheet, value, fieldtype):
	"""One cell, with a number format where the raw value would read badly."""
	from openpyxl.cell import WriteOnlyCell

	value = _cell_value(value, fieldtype)
	number_format = NUMBER_FORMATS.get(fieldtype)
	if value is None or not number_format:
		return value

	cell = WriteOnlyCell(sheet, value=value)
	cell.number_format = number_format
	return cell


def _fieldtypes(columns):
	types = {df.fieldname: df.fieldtype for df in _meta().fields}
	types.setdefault("name", "Data")
	return [types.get(fieldname, "Data") for fieldname in columns]


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------


def write_workbook(filters, columns, path, batch_size=None):
	"""Write the export to `path` in write only mode. Returns the row count."""
	from openpyxl import Workbook
	from openpyxl.cell import WriteOnlyCell
	from openpyxl.styles import Font

	workbook = Workbook(write_only=True)
	sheet = workbook.create_sheet(SHEET_NAME)

	header_font = Font(bold=True)
	header = []
	for label in column_labels(columns):
		cell = WriteOnlyCell(sheet, value=label)
		cell.font = header_font
		header.append(cell)
	sheet.append(header)

	fieldtypes = _fieldtypes(columns)
	rows = 0
	saved = False
	try:
		for record in iter_records(filters, columns, batch_size=batch_size):
			sheet.append(
				[
					_build_cell(sheet, record.get(fieldname), fieldtype)
					for fieldname, fieldtype in zip(columns, fieldtypes)
				]
			)
			rows += 1

		workbook.save(path)
		saved = True
	finally:
		if not saved:
			# A write only sheet holds open lxml stream writers that save()
			# would have closed. Abandoning the workbook on an error -- the row
			# cap, a query failure part way through -- otherwise surfaces later
			# as an ignored exception during garbage collection.
			try:
				sheet.close()
			except Exception:
				pass
		workbook.close()

	return rows


def export_filename(prefix="employee-timeclock"):
	stamp = now_datetime().strftime("%Y%m%d-%H%M%S")
	return f"{prefix}-{stamp}.xlsx"


def _stream_and_delete(path, chunk_size=STREAM_CHUNK_SIZE):
	"""Yield the finished workbook in chunks, then remove it from disk."""

	def generator():
		try:
			with open(path, "rb") as handle:
				while True:
					chunk = handle.read(chunk_size)
					if not chunk:
						break
					yield chunk
		finally:
			try:
				os.remove(path)
			except OSError:
				pass

	return generator()


def build_export_response(raw_filters=None, raw_columns=None, filename=None, batch_size=None):
	"""Permission checked XLSX export, returned as a streaming HTTP response."""
	from werkzeug.wrappers import Response

	frappe.has_permission(TRACKING_DOCTYPE, ptype="export", throw=True)
	_guard_export_rate()

	filters = parse_filters(raw_filters)
	columns = resolve_columns(raw_columns)
	filename = filename or export_filename()

	handle, path = tempfile.mkstemp(suffix=".xlsx", prefix="timeclock-export-")
	os.close(handle)

	try:
		rows = write_workbook(filters, columns, path, batch_size=batch_size)
	except Exception:
		# Nothing is streamed, so the half written file has to go now.
		try:
			os.remove(path)
		except OSError:
			pass
		raise

	_log_export(filters, columns, rows)

	# Read before the generator starts, since streaming deletes the file.
	size = os.path.getsize(path)

	response = Response(
		_stream_and_delete(path),
		mimetype=XLSX_MIMETYPE,
		direct_passthrough=True,
	)
	response.headers.add("Content-Disposition", "attachment", filename=filename)
	response.headers["Content-Length"] = str(size)
	response.headers["X-Row-Count"] = str(rows)
	# The workbook holds wage data: never let a proxy or the browser keep it.
	response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
	response.headers["X-Content-Type-Options"] = "nosniff"
	return response


def _log_export(filters, columns, rows):
	"""Record who exported what, so payroll data access is auditable."""
	try:
		from frappe.core.doctype.access_log.access_log import make_access_log

		make_access_log(
			doctype=TRACKING_DOCTYPE,
			file_type="XLSX",
			method="Employee Timeclock Export",
			filters=frappe.as_json({"filters": filters, "columns": columns, "rows": rows}),
		)
	except Exception:
		# An audit trail failure must not deny the export to a permitted user.
		frappe.log_error(frappe.get_traceback(), "Timeclock export access log failed")
