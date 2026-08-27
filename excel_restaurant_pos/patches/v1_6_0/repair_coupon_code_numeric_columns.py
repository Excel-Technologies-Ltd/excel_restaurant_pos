"""Sanitize Coupon Code numeric columns before schema sync.

Fixture sync updates Custom Fields and triggers `frappe.db.updatedb("Coupon Code")`,
which ALTERs Float/Currency columns to decimal(21,9). Production rows with empty
strings or other non-numeric values in varchar-backed columns cause:

  Data truncated for column 'custom_order_status' at row N

Clean bad values to 0 before migrate continues.
"""

from __future__ import annotations

import frappe


# Columns that fixtures define as Float/Currency and migrate tries to cast to decimal.
COUPON_NUMERIC_COLUMNS = (
	"custom_order_status",
	"custom_available_balance",
	"custom_discount_amount",
	"custom_disc_upto_amount",
	"custom_minimum_subtotal",
)


def _column_exists(column: str) -> bool:
	return bool(
		frappe.db.sql(
			"""
			SELECT 1
			FROM information_schema.COLUMNS
			WHERE TABLE_SCHEMA = DATABASE()
				AND TABLE_NAME = %s
				AND COLUMN_NAME = %s
			LIMIT 1
			""",
			("tabCoupon Code", column),
		)
	)


def _column_data_type(column: str) -> str | None:
	row = frappe.db.sql(
		"""
		SELECT DATA_TYPE
		FROM information_schema.COLUMNS
		WHERE TABLE_SCHEMA = DATABASE()
			AND TABLE_NAME = %s
			AND COLUMN_NAME = %s
		LIMIT 1
		""",
		("tabCoupon Code", column),
	)
	return row[0][0] if row else None


def _sanitize_column(column: str) -> int:
	"""Set empty / non-numeric values to 0. Returns rows touched (approx)."""
	if not _column_exists(column):
		return 0

	data_type = (_column_data_type(column) or "").lower()
	# Only string-like columns need sanitizing before decimal ALTER.
	if data_type not in ("varchar", "text", "longtext", "mediumtext", "char"):
		# Still clear NULLs that block NOT NULL defaults on some MariaDB modes
		frappe.db.sql(
			f"""
			UPDATE `tabCoupon Code`
			SET `{column}` = 0
			WHERE `{column}` IS NULL
			"""
		)
		return 0

	# Empty string, whitespace, or non-numeric → 0
	frappe.db.sql(
		f"""
		UPDATE `tabCoupon Code`
		SET `{column}` = '0'
		WHERE `{column}` IS NULL
			OR TRIM(`{column}`) = ''
			OR TRIM(`{column}`) NOT REGEXP '^-?[0-9]+(\\.[0-9]+)?$'
		"""
	)
	return 1


def execute():
	if not frappe.db.exists("DocType", "Coupon Code"):
		return

	touched = 0
	for column in COUPON_NUMERIC_COLUMNS:
		try:
			touched += _sanitize_column(column)
		except Exception:
			frappe.log_error(
				title=f"repair_coupon_code_numeric_columns:{column}",
				message=frappe.get_traceback(),
			)

	if touched:
		frappe.db.commit()
