# Copyright (c) 2026, Sohanur Rahman and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, nowtime


PNL_NAMING_SERIES = {
	"Income": "INC-.YYYY.-.####",
	"Expense": "EXP-.YYYY.-.####",
}


def get_naming_series_for_pnl_type(pnl_type):
	series = PNL_NAMING_SERIES.get(pnl_type)
	if not series:
		frappe.throw(
			frappe._("pnl_type must be 'Income' or 'Expense'"),
			frappe.ValidationError,
		)
	return series


class PnLEntry(Document):
	def before_insert(self):
		# JSON defaults handle this; fallback just in case
		if not self.posting_date:
			self.posting_date = nowdate()
		if not self.posting_time:
			self.posting_time = nowtime()
		self._set_naming_series()

	def after_insert(self):
		pass

	def validate(self):
		self._set_naming_series()
		self._validate_categories()
		self._calculate_totals()

	def on_submit(self):
		self._calculate_totals()

	def on_cancel(self):
		pass

	def on_amend(self):
		self.posting_date = nowdate()
		self.posting_time = nowtime()

	# ------------------------------------------------------------------
	# Private helpers
	# ------------------------------------------------------------------

	def _set_naming_series(self):
		if not self.pnl_type or not self.is_new():
			return

		self.naming_series = get_naming_series_for_pnl_type(self.pnl_type)

	def _validate_categories(self):
		"""Ensure type / sub_type consistency in child rows."""
		self._check_rows(self.income_items or [], "Income")
		self._check_rows(self.expense_items or [], "Expense")

	def _check_rows(self, rows, section):
		for row in rows:
			if not row.type:
				frappe.throw(
					frappe._(
						"<b>{section} Items — Row #{idx}:</b> Please select a <b>Type</b> before saving."
					).format(section=section, idx=row.idx),
					title=frappe._("Missing Type"),
				)

			if not row.sub_type:
				frappe.throw(
					frappe._(
						"<b>{section} Items — Row #{idx}:</b> Please select a <b>Sub Type</b> for Type <b>{type}</b>."
					).format(section=section, idx=row.idx, type=row.type),
					title=frappe._("Missing Sub Type"),
				)

			sub = frappe.db.get_value(
				"PnL Category",
				row.sub_type,
				["parent_pnl_category", "is_group"],
				as_dict=True,
			)

			if not sub:
				frappe.throw(
					frappe._(
						"<b>{section} Items — Row #{idx}:</b> Sub Type <b>{sub}</b> does not exist."
					).format(section=section, idx=row.idx, sub=row.sub_type),
					title=frappe._("Invalid Sub Type"),
				)

			if sub.parent_pnl_category != row.type:
				frappe.throw(
					frappe._(
						"<b>{section} Items — Row #{idx}:</b> Sub Type <b>{sub}</b> does not belong to Type <b>{type}</b>. "
						"Please choose a Sub Type under <b>{type}</b>."
					).format(
						section=section, idx=row.idx, sub=row.sub_type, type=row.type
					),
					title=frappe._("Sub Type Mismatch"),
				)

			if sub.is_group:
				frappe.throw(
					frappe._(
						"<b>{section} Items — Row #{idx}:</b> <b>{sub}</b> is a category group and cannot be used as a Sub Type. "
						"Please select a leaf-level Sub Type."
					).format(section=section, idx=row.idx, sub=row.sub_type),
					title=frappe._("Group Not Allowed"),
				)

	def _calculate_totals(self):
		self.total_income = sum(row.amount or 0 for row in (self.income_items or []))
		self.total_expense = sum(row.amount or 0 for row in (self.expense_items or []))
		self.net_profit_loss = self.total_income - self.total_expense
