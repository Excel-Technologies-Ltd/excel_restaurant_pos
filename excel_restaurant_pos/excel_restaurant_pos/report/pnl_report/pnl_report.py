# Copyright (c) 2026, Sohanur Rahman and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	filters = filters or {}
	validate_filters(filters)

	columns = get_columns()
	data = get_data(filters)
	report_summary = get_report_summary(data)
	chart = get_chart(data)

	return columns, data, None, chart, report_summary


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def get_columns():
	return [
		{
			"label": _("Particulars"),
			"fieldname": "particulars",
			"fieldtype": "Data",
			"width": 340,
		},
		{
			"label": _("Type"),
			"fieldname": "category_type",
			"fieldtype": "Link",
			"options": "PnL Category",
			"width": 180,
		},
		{
			"label": _("Sub Type"),
			"fieldname": "category_sub_type",
			"fieldtype": "Link",
			"options": "PnL Category",
			"width": 180,
		},
		{
			"label": _("Entry"),
			"fieldname": "entry_id",
			"fieldtype": "Link",
			"options": "PnL Entry",
			"width": 150,
		},
		{
			"label": _("Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("Amount"),
			"fieldname": "amount",
			"fieldtype": "Currency",
			"width": 140,
		},
	]


# ---------------------------------------------------------------------------
# Data builder
# ---------------------------------------------------------------------------

def get_data(filters):
	rows = []

	income_entries = _fetch_entries("income", filters)
	rows += _build_section_rows("Income", income_entries, "income_type", "income_sub_type")

	expense_entries = _fetch_entries("expense", filters)
	rows += _build_section_rows("Expense", expense_entries, "expense_type", "expense_sub_type")

	# Net row
	total_income = sum(r["amount"] for r in rows if r.get("_section") == "income_total")
	total_expense = sum(r["amount"] for r in rows if r.get("_section") == "expense_total")
	net = flt(total_income - total_expense, 2)

	rows.append(_separator())
	net_label = _("Net Profit") if net >= 0 else _("Net Loss")
	rows.append({
		"particulars": net_label,
		"amount": net,
		"bold": 1,
		"indent": 0,
		"_section": "net",
	})

	return rows


def _build_section_rows(section_label, entries, type_key, sub_type_key):
	"""
	Returns a flat list of display rows for one section (Income or Expense).

	Structure:
	  ── INCOME (header, bold)
	     ── Revenue (type group, bold, indent 1)
	        ── Dine-In    entry_id  date  amount    (leaf, indent 2)
	        ── ...
	        Sub-total: Revenue                      (bold, indent 1)
	     ── ...
	  Total Income                                  (bold, indent 0)
	"""
	section_key = section_label.lower()
	rows = []

	# Section header
	rows.append({
		"particulars": section_label.upper(),
		"bold": 1,
		"indent": 0,
		"_section": section_key + "_header",
	})

	if not entries:
		rows.append({
			"particulars": _("No entries found"),
			"indent": 1,
			"_section": section_key,
		})
		rows.append({
			"particulars": f"Total {section_label}",
			"amount": 0.0,
			"bold": 1,
			"indent": 0,
			"_section": section_key + "_total",
		})
		return rows

	# Group by type → sub_type
	type_map = {}
	for row in entries:
		t = row.get(type_key) or _("Unclassified")
		st = row.get(sub_type_key) or _("Unclassified")
		type_map.setdefault(t, {})
		type_map[t].setdefault(st, [])
		type_map[t][st].append(row)

	section_total = 0.0

	for type_name, sub_types in type_map.items():
		type_total = sum(
			flt(r.get("amount"), 2)
			for sub_rows in sub_types.values()
			for r in sub_rows
		)
		section_total += type_total

		# Type group header
		rows.append({
			"particulars": type_name,
			"category_type": type_name,
			"amount": type_total,
			"bold": 1,
			"indent": 1,
			"_section": section_key,
		})

		for sub_type_name, sub_rows in sub_types.items():
			sub_total = flt(sum(flt(r.get("amount"), 2) for r in sub_rows), 2)

			# Sub-type group header (only show if more than 1 entry)
			if len(sub_rows) > 1:
				rows.append({
					"particulars": sub_type_name,
					"category_type": type_name,
					"category_sub_type": sub_type_name,
					"amount": sub_total,
					"bold": 1,
					"indent": 2,
					"_section": section_key,
				})

			for r in sub_rows:
				rows.append({
					"particulars": sub_type_name if len(sub_rows) == 1 else "",
					"category_type": type_name,
					"category_sub_type": sub_type_name,
					"entry_id": r.get("entry_id"),
					"posting_date": r.get("posting_date"),
					"amount": flt(r.get("amount"), 2),
					"indent": 3 if len(sub_rows) > 1 else 2,
					"_section": section_key,
				})

	# Section total row
	rows.append({
		"particulars": f"Total {section_label}",
		"amount": flt(section_total, 2),
		"bold": 1,
		"indent": 0,
		"_section": section_key + "_total",
	})

	return rows


def _separator():
	return {"particulars": "", "bold": 0, "indent": 0, "_section": "separator"}


# ---------------------------------------------------------------------------
# SQL fetchers
# ---------------------------------------------------------------------------

def _fetch_entries(section, filters):
	start_date = filters.get("from_date")
	end_date = filters.get("to_date")
	type_filter = filters.get("type") or None
	sub_type_filter = filters.get("sub_type") or None
	company = filters.get("company") or None

	if section == "income":
		return _fetch_income(start_date, end_date, type_filter, sub_type_filter, company)
	return _fetch_expense(start_date, end_date, type_filter, sub_type_filter, company)


def _fetch_income(start_date, end_date, type_filter, sub_type_filter, company):
	extra = ""
	values = {"start_date": start_date, "end_date": end_date}

	if type_filter:
		extra += " AND pii.type = %(type_filter)s"
		values["type_filter"] = type_filter
	if sub_type_filter:
		extra += " AND pii.sub_type = %(sub_type_filter)s"
		values["sub_type_filter"] = sub_type_filter
	if company:
		extra += " AND pe.company = %(company)s"
		values["company"] = company

	return frappe.db.sql(
		f"""
		SELECT
			pe.name       AS entry_id,
			pe.posting_date,
			pe.posting_time,
			pe.company,
			pii.type      AS income_type,
			pii.sub_type  AS income_sub_type,
			pii.amount,
			pii.description
		FROM `tabPnL Entry` pe
		INNER JOIN `tabPnL Income Item` pii ON pii.parent = pe.name
		WHERE pe.docstatus = 1
		  AND pe.posting_date BETWEEN %(start_date)s AND %(end_date)s
		  {extra}
		ORDER BY pe.posting_date DESC, pe.posting_time DESC
		""",
		values,
		as_dict=True,
	)


def _fetch_expense(start_date, end_date, type_filter, sub_type_filter, company):
	extra = ""
	values = {"start_date": start_date, "end_date": end_date}

	if type_filter:
		extra += " AND pei.type = %(type_filter)s"
		values["type_filter"] = type_filter
	if sub_type_filter:
		extra += " AND pei.sub_type = %(sub_type_filter)s"
		values["sub_type_filter"] = sub_type_filter
	if company:
		extra += " AND pe.company = %(company)s"
		values["company"] = company

	return frappe.db.sql(
		f"""
		SELECT
			pe.name       AS entry_id,
			pe.posting_date,
			pe.posting_time,
			pe.company,
			pei.type      AS expense_type,
			pei.sub_type  AS expense_sub_type,
			pei.amount,
			pei.description
		FROM `tabPnL Entry` pe
		INNER JOIN `tabPnL Expense Item` pei ON pei.parent = pe.name
		WHERE pe.docstatus = 1
		  AND pe.posting_date BETWEEN %(start_date)s AND %(end_date)s
		  {extra}
		ORDER BY pe.posting_date DESC, pe.posting_time DESC
		""",
		values,
		as_dict=True,
	)


# ---------------------------------------------------------------------------
# Report summary (tiles shown at the top of the report)
# ---------------------------------------------------------------------------

def get_report_summary(data):
	total_income = sum(r["amount"] for r in data if r.get("_section") == "income_total")
	total_expense = sum(r["amount"] for r in data if r.get("_section") == "expense_total")
	net = flt(total_income - total_expense, 2)

	return [
		{
			"value": flt(total_income, 2),
			"label": _("Total Income"),
			"datatype": "Currency",
			"indicator": "Blue",
		},
		{
			"value": flt(total_expense, 2),
			"label": _("Total Expense"),
			"datatype": "Currency",
			"indicator": "Red",
		},
		{
			"value": net,
			"label": _("Net Profit") if net >= 0 else _("Net Loss"),
			"datatype": "Currency",
			"indicator": "Green" if net >= 0 else "Red",
		},
	]


# ---------------------------------------------------------------------------
# Chart (simple bar — Total Income, Total Expense, Net Profit/Loss)
# ---------------------------------------------------------------------------

def get_chart(data):
	total_income = sum(r["amount"] for r in data if r.get("_section") == "income_total")
	total_expense = sum(r["amount"] for r in data if r.get("_section") == "expense_total")
	net = flt(total_income - total_expense, 2)

	if not total_income and not total_expense:
		return None

	net_color = "#28a745" if net >= 0 else "#dc3545"

	return {
		"data": {
			"labels": [_("Income"), _("Expense"), _("Net Profit/Loss")],
			"datasets": [
				{"name": _("Income"),          "values": [flt(total_income, 2), 0, 0]},
				{"name": _("Expense"),         "values": [0, flt(total_expense, 2), 0]},
				{"name": _("Net Profit/Loss"), "values": [0, 0, net]},
			],
		},
		"type": "bar",
		"colors": ["#2196f3", "#fd7e14", net_color],
		"barOptions": {"stacked": 1},
	}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_filters(filters):
	if not filters.get("from_date"):
		frappe.throw(_("Please set <b>From Date</b>"), title=_("Missing Filter"))
	if not filters.get("to_date"):
		frappe.throw(_("Please set <b>To Date</b>"), title=_("Missing Filter"))
	if getdate(filters["from_date"]) > getdate(filters["to_date"]):
		frappe.throw(
			_("<b>From Date</b> cannot be after <b>To Date</b>"),
			title=_("Invalid Date Range"),
		)
	if filters.get("sub_type") and not filters.get("type"):
		frappe.throw(
			_("Please select a <b>Type</b> before filtering by <b>Sub Type</b>"),
			title=_("Missing Filter"),
		)
