# Copyright (c) 2026, Excel and Contributors
# See license.txt

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.sql_procedures.sync import (
	get_sql_files,
	split_sql_statements,
)


class TestSqlStatementSplitter(FrappeTestCase):
	def test_plain_semicolon_file(self):
		self.assertEqual(split_sql_statements("SELECT 1;\nSELECT 2;\n"), ["SELECT 1", "SELECT 2"])

	def test_missing_trailing_delimiter_still_yields_the_statement(self):
		self.assertEqual(split_sql_statements("SELECT 1"), ["SELECT 1"])

	def test_comments_only_file_yields_nothing(self):
		self.assertEqual(split_sql_statements("-- nothing\n/* also nothing */\n"), [])
		self.assertEqual(split_sql_statements(""), [])

	def test_delimiter_directive_is_not_sent_to_the_server(self):
		statements = split_sql_statements(
			"DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1; END //\nDELIMITER ;\nSELECT 9;\n"
		)
		self.assertEqual(len(statements), 2)
		for statement in statements:
			for line in statement.splitlines():
				self.assertFalse(line.strip().upper().startswith("DELIMITER"))

	def test_procedure_body_keeps_its_internal_semicolons(self):
		statements = split_sql_statements(
			"DELIMITER //\nCREATE PROCEDURE p()\nBEGIN\n  SET @a = 1;\n  SET @b = 2;\nEND //\nDELIMITER ;\n"
		)
		self.assertEqual(len(statements), 1)
		self.assertEqual(statements[0].count(";"), 2)
		self.assertTrue(statements[0].rstrip().endswith("END"))

	def test_delimiter_switches_back(self):
		statements = split_sql_statements(
			"DROP PROCEDURE IF EXISTS `p`;\nDELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1; END //\nDELIMITER ;\n"
		)
		self.assertEqual(len(statements), 2)
		self.assertTrue(statements[0].startswith("DROP PROCEDURE"))
		self.assertTrue(statements[1].startswith("CREATE PROCEDURE"))


class TestShippedSqlFiles(FrappeTestCase):
	def test_every_shipped_file_parses(self):
		files = get_sql_files()
		self.assertTrue(files, "no .sql files found under report_sql/")

		for path in files:
			with open(path, encoding="utf-8") as handle:
				statements = split_sql_statements(handle.read())

			name = os.path.basename(path)
			self.assertTrue(statements, f"{name} produced no statements")
			for statement in statements:
				self.assertFalse(
					statement.rstrip().endswith("//"),
					f"{name} left a delimiter in a statement",
				)

	def test_timeclock_summary_procedure_is_shipped(self):
		names = [os.path.basename(path) for path in get_sql_files()]
		self.assertIn("GetEmployeeTimeclockSummary.sql", names)
