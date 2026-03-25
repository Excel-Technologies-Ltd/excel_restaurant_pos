# Copyright (c) 2026, Sohanur Rahman and contributors
# For license information, please see license.txt

import frappe
from frappe.utils.nestedset import NestedSet


class PnLCategory(NestedSet):
	nsm_parent_field = "parent_pnl_category"

	def validate(self):
		if self.parent_pnl_category:
			parent = frappe.get_doc("PnL Category", self.parent_pnl_category)
			if parent.pnl_type != self.pnl_type:
				frappe.throw(
					frappe._(
						"PnL Type must match parent category. Parent is '{0}'.".format(parent.pnl_type)
					)
				)
		if self.is_group == 0 and not self.parent_pnl_category:
			frappe.throw(frappe._("A non-group PnL Category must have a parent category."))


def get_children(doctype, parent=None, is_root=False, **kwargs):
	filters = [["docstatus", "<", 2]]
	if parent and not is_root:
		filters.append(["parent_pnl_category", "=", parent])
	else:
		filters.append(["ifnull(parent_pnl_category, '')", "=", ""])

	rows = frappe.get_all(
		doctype,
		fields=["name", "category_name", "is_group", "pnl_type"],
		filters=filters,
		order_by="category_name",
	)

	# Frappe tree view requires `value` (the doc name) and `title` (display label)
	for row in rows:
		row["value"] = row["name"]
		row["title"] = row.get("category_name") or row["name"]

	return rows


def add_node():
	from frappe.desk.treeview import make_tree_args
	args = frappe.form_dict
	args = make_tree_args(**args)
	if args.is_root:
		args.parent_pnl_category = None
	frappe.get_doc(args).insert()
