# Copyright (c) 2026, Excel and Contributors
# See license.txt

import os
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.sql_procedures.sync import (
	get_sql_files,
	install_sql_file,
	split_sql_statements,
	strip_leading_comments,
)

MODULE = "excel_restaurant_pos.shared.sql_procedures.sync"


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


class TestLeadingComments(FrappeTestCase):
	"""frappe reads a query's type from its first token, so a leading comment hides it."""

	def test_comments_are_dropped(self):
		self.assertEqual(
			strip_leading_comments("-- why\n-- and how\nDROP PROCEDURE IF EXISTS `x`"),
			"DROP PROCEDURE IF EXISTS `x`",
		)

	def test_statement_without_comments_is_unchanged(self):
		self.assertEqual(strip_leading_comments("SELECT 1"), "SELECT 1")

	def test_comment_only_statement_becomes_empty(self):
		self.assertEqual(strip_leading_comments("-- nothing\n-- here\n"), "")

	def test_inner_comments_are_kept(self):
		statement = "CREATE PROCEDURE p()\nBEGIN\n  -- explain\n  SELECT 1;\nEND"
		self.assertEqual(strip_leading_comments(statement), statement)


class TestInstallUsesDdlPath(FrappeTestCase):
	def test_statements_go_through_sql_ddl(self):
		"""Plain db.sql raises ImplicitCommitError once a transaction has writes."""
		path = get_sql_files()[0]

		with patch(f"{MODULE}.frappe.db.sql_ddl") as sql_ddl:
			with patch(f"{MODULE}.frappe.db.sql") as plain_sql:
				count = install_sql_file(path)

		self.assertEqual(sql_ddl.call_count, count)
		plain_sql.assert_not_called()

	def test_statements_reach_the_server_without_leading_comments(self):
		path = get_sql_files()[0]

		with patch(f"{MODULE}.frappe.db.sql_ddl") as sql_ddl:
			install_sql_file(path)

		for call in sql_ddl.call_args_list:
			statement = call.args[0]
			self.assertFalse(statement.lstrip().startswith("--"), statement[:60])
