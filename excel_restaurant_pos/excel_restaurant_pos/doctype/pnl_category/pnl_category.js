// Copyright (c) 2026, Sohanur Rahman and contributors
// For license information, please see license.txt

frappe.treeview_settings["PnL Category"] = {
	breadcrumb: "PnL Category",
	get_tree_root: false,

	onload(treeview) {
		treeview.page.add_inner_button(__("View List"), () => {
			frappe.set_route("List", "PnL Category");
		});
	},
};
