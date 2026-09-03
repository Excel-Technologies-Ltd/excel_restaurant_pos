# Copyright (c) 2026, Excel and Contributors
# See license.txt

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.api.report.get_employee_timeclock_summary import (
	get_employee_timeclock_summary,
)

MODULE = "excel_restaurant_pos.api.report.get_employee_timeclock_summary"

SAMPLE = {
	"date_range": {"start_date": "2026-09-01", "end_date": "2026-09-02", "total_days": 2},
	"pagination": {"page": 1, "pageSize": 20, "totalPages": 1},
	"date_summary": None,
	"employees": [{"employee_id": "6", "employee_name": "Staff", "daily_slots": None}],
}


class TestTimeclockSummaryReport(FrappeTestCase):
	def test_report_permission_is_required(self):
		with patch(f"{MODULE}.frappe.has_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				get_employee_timeclock_summary()

	def test_arguments_are_normalised_before_the_call(self):
		with patch(f"{MODULE}.frappe.has_permission", return_value=True):
			with patch(f"{MODULE}._call_procedure", return_value=[]) as call:
				get_employee_timeclock_summary(
					start_date="2026-09-01", end_date="2026-09-30", employee_id="  6 ", page="2", page_size="50"
				)

		start, end, employee, page, page_size = call.call_args.args[0]
		self.assertEqual(str(start), "2026-09-01")
		self.assertEqual(str(end), "2026-09-30")
		self.assertEqual(employee, "6")
		self.assertEqual(page, 2)
		self.assertEqual(page_size, 50)

	def test_blank_employee_becomes_null(self):
		with patch(f"{MODULE}.frappe.has_permission", return_value=True):
			with patch(f"{MODULE}._call_procedure", return_value=[]) as call:
				get_employee_timeclock_summary(employee_id="   ")

		self.assertIsNone(call.call_args.args[0][2])

	def test_page_size_is_capped_and_page_floored(self):
		with patch(f"{MODULE}.frappe.has_permission", return_value=True):
			with patch(f"{MODULE}._call_procedure", return_value=[]) as call:
				get_employee_timeclock_summary(page="0", page_size="9999")

		_start, _end, _employee, page, page_size = call.call_args.args[0]
		self.assertEqual(page, 1)
		self.assertEqual(page_size, 200)

	def test_reversed_date_range_is_rejected(self):
		with patch(f"{MODULE}.frappe.has_permission", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				get_employee_timeclock_summary(start_date="2026-09-30", end_date="2026-09-01")

	def test_no_rows_returns_an_empty_shape(self):
		with patch(f"{MODULE}.frappe.has_permission", return_value=True):
			with patch(f"{MODULE}._call_procedure", return_value=[{"json_result": None}]):
				result = get_employee_timeclock_summary(start_date="2026-09-01", end_date="2026-09-02")

		self.assertEqual(result["employees"], [])
		self.assertEqual(result["date_summary"], [])
		self.assertEqual(result["pagination"]["totalPages"], 0)

	def test_json_payload_is_parsed_and_nulls_become_lists(self):
		with patch(f"{MODULE}.frappe.has_permission", return_value=True):
			with patch(
				f"{MODULE}._call_procedure", return_value=[{"json_result": json.dumps(SAMPLE)}]
			):
				result = get_employee_timeclock_summary()

		self.assertEqual(result["date_summary"], [])
		self.assertEqual(result["employees"][0]["daily_slots"], [])
		self.assertEqual(result["date_range"]["total_days"], 2)

	def test_bytes_payload_is_decoded(self):
		with patch(f"{MODULE}.frappe.has_permission", return_value=True):
			with patch(
				f"{MODULE}._call_procedure",
				return_value=[{"json_result": json.dumps(SAMPLE).encode("utf-8")}],
			):
				result = get_employee_timeclock_summary()

		self.assertEqual(result["employees"][0]["employee_id"], "6")
