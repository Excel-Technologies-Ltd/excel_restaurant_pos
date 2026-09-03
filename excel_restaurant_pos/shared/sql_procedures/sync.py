"""Install the stored procedures kept as .sql files under `report_sql/`.

Procedures used to be pasted inline into a patch, which meant a new report or a
tweak to an existing one needed a new patch module every time. The .sql files are
now the source of truth: drop one in `excel_restaurant_pos/report_sql/` and the
next `bench migrate` installs it.

Writing a file
--------------
`DELIMITER` is a mysql client directive, not SQL, so it is handled here rather
than sent to the server. Two rules keep a file parseable:

* a statement terminator ends its line -- one statement per terminator;
* a `DROP PROCEDURE` before the body belongs *above* `DELIMITER //`, since while
  `//` is active a trailing `;` no longer ends a statement.

Files are re-installed on every migrate. `DROP ... IF EXISTS` followed by
`CREATE` is idempotent and costs milliseconds, so nothing tracks which version
was installed last -- the file on disk is always what the database gets.
"""

from __future__ import annotations

import os
from glob import glob

import frappe
from frappe import _

APP_NAME = "excel_restaurant_pos"
SQL_FOLDER = "report_sql"
DEFAULT_DELIMITER = ";"


def get_sql_folder() -> str:
	return frappe.get_app_path(APP_NAME, SQL_FOLDER)


def get_sql_files() -> list:
	"""Every .sql file to install, in a stable order."""
	folder = get_sql_folder()
	if not os.path.isdir(folder):
		return []
	return sorted(glob(os.path.join(folder, "*.sql")))


def _is_only_comments(statement: str) -> bool:
	for line in statement.splitlines():
		line = line.strip()
		if line and not line.startswith("--") and not line.startswith("/*"):
			return False
	return True


def split_sql_statements(sql_text: str) -> list:
	"""Split a .sql file into statements, honouring DELIMITER directives."""
	delimiter = DEFAULT_DELIMITER
	statements: list = []
	buffer: list = []

	def flush():
		statement = "\n".join(buffer).strip()
		buffer.clear()
		if statement and not _is_only_comments(statement):
			statements.append(statement)

	for line in sql_text.splitlines():
		stripped = line.strip()

		if stripped.upper().startswith("DELIMITER"):
			# A client side directive. It can only appear between statements, so
			# whatever is buffered is already complete.
			flush()
			parts = stripped.split(None, 1)
			delimiter = parts[1].strip() if len(parts) > 1 else DEFAULT_DELIMITER
			continue

		if stripped and stripped.endswith(delimiter):
			trimmed = line.rstrip()
			buffer.append(trimmed[: len(trimmed) - len(delimiter)])
			flush()
			continue

		buffer.append(line)

	flush()
	return statements


def install_sql_file(path: str) -> int:
	"""Run every statement in one .sql file. Returns how many were run."""
	with open(path, encoding="utf-8") as handle:
		statements = split_sql_statements(handle.read())

	if not statements:
		frappe.throw(
			_("{0} contains no SQL statements").format(os.path.basename(path)),
			frappe.ValidationError,
		)

	for statement in statements:
		try:
			frappe.db.sql(statement)
		except Exception as exc:
			# Name the file: the traceback alone only shows the SQL text.
			frappe.throw(
				_("Failed to install {0}: {1}").format(os.path.basename(path), exc),
				frappe.ValidationError,
			)

	return len(statements)


def sync_sql_objects():
	"""Install every `report_sql/*.sql` file. Runs after each migrate."""
	installed = []
	for path in get_sql_files():
		count = install_sql_file(path)
		name = os.path.basename(path)
		installed.append(name)
		print(f"Installed {SQL_FOLDER}/{name} ({count} statement(s))")

	if not installed:
		print(f"No .sql files found in {SQL_FOLDER}/")

	return installed
