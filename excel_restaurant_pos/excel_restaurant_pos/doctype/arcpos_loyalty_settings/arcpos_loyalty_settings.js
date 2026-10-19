// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.ui.form.on("ArcPOS Loyalty Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Post Liability True-up Now"), () =>
			frappe.call({
				method: "excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_settings.arcpos_loyalty_settings.post_true_up_now",
			}).then((r) => r.message && frappe.set_route("Form", "ArcPOS Loyalty Liability Run", r.message))
		);
	},
});
