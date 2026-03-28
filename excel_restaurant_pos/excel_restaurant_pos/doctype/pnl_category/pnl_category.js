// Copyright (c) 2026, Sohanur Rahman and contributors
// For license information, please see license.txt

frappe.ui.form.on("PnL Category", {
	pnl_type(frm) {
		// Clear parent when type changes so stale value isn't carried over
		frm.set_value("parent_pnl_category", "");
		frm.fields_dict.parent_pnl_category.get_query = () => ({
			filters: { pnl_type: frm.doc.pnl_type, is_group: 1 },
		});
	},

	onload(frm) {
		frm.fields_dict.parent_pnl_category.get_query = () => ({
			filters: { pnl_type: frm.doc.pnl_type || "__never__", is_group: 1 },
		});
	},
});

frappe.treeview_settings["PnL Category"] = {
	breadcrumb: "PnL Category",
	get_tree_root: false,

	onload(treeview) {
		treeview.page.add_inner_button(__("View List"), () => {
			frappe.set_route("List", "PnL Category");
		});
	},
};
