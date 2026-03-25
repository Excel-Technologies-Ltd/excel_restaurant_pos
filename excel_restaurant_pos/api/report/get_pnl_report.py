# Copyright (c) 2026, Sohanur Rahman and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt
from datetime import datetime

from .report_helper import (
	validate_required_yyyy_mm_dd,
	validate_start_end_date,
	normalize_optional_string,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_pnl_report(
	start_date=None,
	end_date=None,
	pnl_section=None,
	type=None,
	sub_type=None,
	company=None,
):
	"""
	Profit & Loss report with flexible filtering.

	Query Parameters
	----------------
	start_date   : YYYY-MM-DD  (required)
	end_date     : YYYY-MM-DD  (required, inclusive)
	pnl_section  : "income" | "expense" | "both"  (default: "both")
	type         : PnL Category name (group-level filter, optional)
	sub_type     : PnL Category name (leaf-level filter, optional)
	company      : Company name (optional)

	Response
	--------
	{
	    "date_range"      : "25th March 2026 to 25th March 2026",
	    "start_date"      : "2026-03-25",
	    "end_date"        : "2026-03-25",
	    "filters_applied" : { ... },
	    "summary"         : { total_income, total_expense, net_profit_loss },
	    "income"          : { total, by_type: [...], entries: [...] },
	    "expense"         : { total, by_type: [...], entries: [...] }
	}
	"""
	# --- Validate & normalise inputs ---
	start_date = validate_required_yyyy_mm_dd("Start Date", start_date)
	end_date = validate_required_yyyy_mm_dd("End Date", end_date)
	validate_start_end_date(start_date, end_date)

	pnl_section = normalize_optional_string(pnl_section) or "both"
	if pnl_section not in ("income", "expense", "both"):
		frappe.throw(
			frappe._("pnl_section must be 'income', 'expense', or 'both'"),
			frappe.ValidationError,
		)

	type = normalize_optional_string(type)
	sub_type = normalize_optional_string(sub_type)
	company = normalize_optional_string(company)

	# sub_type implies that type must also be provided when sub_type is set
	if sub_type and not type:
		frappe.throw(
			frappe._("'type' filter is required when 'sub_type' is specified"),
			frappe.ValidationError,
		)

	try:
		filters_applied = {
			"start_date": start_date,
			"end_date": end_date,
			"pnl_section": pnl_section,
			"type": type,
			"sub_type": sub_type,
			"company": company,
		}

		income_data = {}
		expense_data = {}

		if pnl_section in ("income", "both"):
			income_data = _build_income_data(start_date, end_date, type, sub_type, company)

		if pnl_section in ("expense", "both"):
			expense_data = _build_expense_data(start_date, end_date, type, sub_type, company)

		total_income = flt(income_data.get("total", 0), 2)
		total_expense = flt(expense_data.get("total", 0), 2)

		return {
			"date_range": _format_date_range(start_date, end_date),
			"start_date": start_date,
			"end_date": end_date,
			"filters_applied": filters_applied,
			"summary": {
				"total_income": total_income,
				"total_expense": total_expense,
				"net_profit_loss": flt(total_income - total_expense, 2),
				"is_profit": total_income >= total_expense,
			},
			"income": income_data,
			"expense": expense_data,
		}

	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(
			title="get_pnl_report failed",
			message=frappe.get_traceback(),
		)
		frappe.throw(
			frappe._("Failed to fetch PnL Report. Please contact your system administrator."),
			frappe.ValidationError,
		)


# ---------------------------------------------------------------------------
# PnL Category helper
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_pnl_categories(pnl_type=None, parent=None):
	"""
	Return PnL Categories for populating dropdowns in the frontend.

	Query Parameters
	----------------
	pnl_type : "Income" | "Expense"  (optional — returns all if omitted)
	parent   : PnL Category name     (optional — returns root groups if omitted,
	                                  returns children of 'parent' if provided)

	Response
	--------
	[{ "name", "category_name", "pnl_type", "is_group", "parent_pnl_category" }, ...]
	"""
	pnl_type = normalize_optional_string(pnl_type)
	parent = normalize_optional_string(parent)

	if pnl_type and pnl_type not in ("Income", "Expense"):
		frappe.throw(
			frappe._("pnl_type must be 'Income' or 'Expense'"),
			frappe.ValidationError,
		)

	conditions = []
	values = {}

	if pnl_type:
		conditions.append("pnl_type = %(pnl_type)s")
		values["pnl_type"] = pnl_type

	if parent:
		conditions.append("parent_pnl_category = %(parent)s")
		values["parent"] = parent
	else:
		# Return root-level groups when no parent is given
		conditions.append("(parent_pnl_category IS NULL OR parent_pnl_category = '')")

	where = "WHERE " + " AND ".join(conditions) if conditions else ""

	rows = frappe.db.sql(
		f"""
		SELECT
			name,
			category_name,
			pnl_type,
			is_group,
			parent_pnl_category
		FROM `tabPnL Category`
		{where}
		ORDER BY pnl_type, category_name
		""",
		values,
		as_dict=True,
	)

	return rows


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_income_data(start_date, end_date, type_filter, sub_type_filter, company):
	"""Fetch and structure income entries."""
	entries = _fetch_income_entries(start_date, end_date, type_filter, sub_type_filter, company)
	total = flt(sum(r.amount for r in entries), 2)
	by_type = _group_by_type(entries, "income_type", "income_sub_type")

	return {
		"total": total,
		"by_type": by_type,
		"entries": [_serialise_row(r) for r in entries],
	}


def _build_expense_data(start_date, end_date, type_filter, sub_type_filter, company):
	"""Fetch and structure expense entries."""
	entries = _fetch_expense_entries(start_date, end_date, type_filter, sub_type_filter, company)
	total = flt(sum(r.amount for r in entries), 2)
	by_type = _group_by_type(entries, "expense_type", "expense_sub_type")

	return {
		"total": total,
		"by_type": by_type,
		"entries": [_serialise_row(r) for r in entries],
	}


def _fetch_income_entries(start_date, end_date, type_filter, sub_type_filter, company):
	"""Raw SQL query for income child rows joined to PnL Entry."""
	extra_conditions = ""
	values = {
		"start_date": start_date,
		"end_date": end_date,
	}

	if type_filter:
		extra_conditions += " AND pii.type = %(type_filter)s"
		values["type_filter"] = type_filter

	if sub_type_filter:
		extra_conditions += " AND pii.sub_type = %(sub_type_filter)s"
		values["sub_type_filter"] = sub_type_filter

	if company:
		extra_conditions += " AND pe.company = %(company)s"
		values["company"] = company

	return frappe.db.sql(
		f"""
		SELECT
			pe.name          AS entry_id,
			pe.posting_date,
			pe.posting_time,
			pe.company,
			pii.type         AS income_type,
			pii.sub_type     AS income_sub_type,
			pii.amount,
			pii.description
		FROM `tabPnL Entry` pe
		INNER JOIN `tabPnL Income Item` pii ON pii.parent = pe.name
		WHERE pe.docstatus = 1
		  AND pe.posting_date BETWEEN %(start_date)s AND %(end_date)s
		  {extra_conditions}
		ORDER BY pe.posting_date DESC, pe.posting_time DESC
		""",
		values,
		as_dict=True,
	)


def _fetch_expense_entries(start_date, end_date, type_filter, sub_type_filter, company):
	"""Raw SQL query for expense child rows joined to PnL Entry."""
	extra_conditions = ""
	values = {
		"start_date": start_date,
		"end_date": end_date,
	}

	if type_filter:
		extra_conditions += " AND pei.type = %(type_filter)s"
		values["type_filter"] = type_filter

	if sub_type_filter:
		extra_conditions += " AND pei.sub_type = %(sub_type_filter)s"
		values["sub_type_filter"] = sub_type_filter

	if company:
		extra_conditions += " AND pe.company = %(company)s"
		values["company"] = company

	return frappe.db.sql(
		f"""
		SELECT
			pe.name          AS entry_id,
			pe.posting_date,
			pe.posting_time,
			pe.company,
			pei.type         AS expense_type,
			pei.sub_type     AS expense_sub_type,
			pei.amount,
			pei.description
		FROM `tabPnL Entry` pe
		INNER JOIN `tabPnL Expense Item` pei ON pei.parent = pe.name
		WHERE pe.docstatus = 1
		  AND pe.posting_date BETWEEN %(start_date)s AND %(end_date)s
		  {extra_conditions}
		ORDER BY pe.posting_date DESC, pe.posting_time DESC
		""",
		values,
		as_dict=True,
	)


def _group_by_type(entries, type_key, sub_type_key):
	"""
	Group flat entry rows into:
	[
	    {
	        type: "...",
	        total: 0,
	        sub_types: [
	            { sub_type: "...", total: 0, entries: [...] }
	        ]
	    }
	]
	"""
	type_map = {}

	for row in entries:
		t = row.get(type_key) or "Unclassified"
		st = row.get(sub_type_key) or "Unclassified"

		if t not in type_map:
			type_map[t] = {"type": t, "total": 0.0, "sub_types": {}}

		if st not in type_map[t]["sub_types"]:
			type_map[t]["sub_types"][st] = {"sub_type": st, "total": 0.0, "entries": []}

		amount = flt(row.amount, 2)
		type_map[t]["total"] += amount
		type_map[t]["sub_types"][st]["total"] += amount
		type_map[t]["sub_types"][st]["entries"].append(_serialise_row(row))

	result = []
	for t_data in type_map.values():
		sub_types_list = list(t_data["sub_types"].values())
		for st in sub_types_list:
			st["total"] = flt(st["total"], 2)
		result.append(
			{
				"type": t_data["type"],
				"total": flt(t_data["total"], 2),
				"sub_types": sub_types_list,
			}
		)

	return result


def _serialise_row(row):
	"""Convert a DB row to a plain dict with formatted values."""
	return {
		"entry_id": row.get("entry_id"),
		"posting_date": str(row.get("posting_date") or ""),
		"posting_time": str(row.get("posting_time") or ""),
		"company": row.get("company"),
		"type": row.get("income_type") or row.get("expense_type"),
		"sub_type": row.get("income_sub_type") or row.get("expense_sub_type"),
		"amount": flt(row.get("amount"), 2),
		"description": row.get("description") or "",
	}


def _format_date_range(start_date: str, end_date: str) -> str:
	start = _ordinal_date(start_date)
	end = _ordinal_date(end_date)
	return f"{start} to {end}" if start != end else start


def _ordinal_date(date_str: str) -> str:
	dt = datetime.strptime(date_str, "%Y-%m-%d")
	day = dt.day
	suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
	return f"{day}{suffix} {dt.strftime('%B %Y')}"
