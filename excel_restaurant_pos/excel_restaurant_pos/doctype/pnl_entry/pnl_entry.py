# Copyright (c) 2026, Sohanur Rahman and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, nowdate, nowtime


class PnLEntry(Document):
	def before_insert(self):
		if not self.posting_date:
			self.posting_date = nowdate()
		if not self.posting_time:
			self.posting_time = nowtime()

	def validate(self):
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

	def _validate_categories(self):
		"""Ensure type/sub_type consistency in child rows."""
		for row in self.income_items or []:
			if row.type and row.sub_type:
				sub = frappe.db.get_value(
					"PnL Category",
					row.sub_type,
					["parent_pnl_category", "is_group"],
					as_dict=True,
				)
				if sub and sub.parent_pnl_category != row.type:
					frappe.throw(
						frappe._(
							"Row #{0} in Income Items: Sub Type '{1}' does not belong to Type '{2}'.".format(
								row.idx, row.sub_type, row.type
							)
						)
					)
				if sub and sub.is_group:
					frappe.throw(
						frappe._(
							"Row #{0} in Income Items: Sub Type '{1}' is a group and cannot be used directly.".format(
								row.idx, row.sub_type
							)
						)
					)

		for row in self.expense_items or []:
			if row.type and row.sub_type:
				sub = frappe.db.get_value(
					"PnL Category",
					row.sub_type,
					["parent_pnl_category", "is_group"],
					as_dict=True,
				)
				if sub and sub.parent_pnl_category != row.type:
					frappe.throw(
						frappe._(
							"Row #{0} in Expense Items: Sub Type '{1}' does not belong to Type '{2}'.".format(
								row.idx, row.sub_type, row.type
							)
						)
					)
				if sub and sub.is_group:
					frappe.throw(
						frappe._(
							"Row #{0} in Expense Items: Sub Type '{1}' is a group and cannot be used directly.".format(
								row.idx, row.sub_type
							)
						)
					)

	def _calculate_totals(self):
		self.total_income = sum(row.amount or 0 for row in (self.income_items or []))
		self.total_expense = sum(row.amount or 0 for row in (self.expense_items or []))
		self.net_profit_loss = self.total_income - self.total_expense
