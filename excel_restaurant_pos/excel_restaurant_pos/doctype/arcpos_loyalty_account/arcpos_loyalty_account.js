// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

const ACCOUNT_API = "excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_account.arcpos_loyalty_account";

frappe.ui.form.on("ArcPOS Loyalty Account", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Ledger"), () =>
			frappe.set_route("List", "ArcPOS Loyalty Transaction", { account: frm.doc.name })
		);
		frm.add_custom_button(__("Adjust Points"), () =>
			frappe.new_doc("ArcPOS Loyalty Adjustment", { account: frm.doc.name })
		);

		const call = (method, args, message) =>
			frappe.call({ method: `${ACCOUNT_API}.${method}`, args: { account: frm.doc.name, ...args } }).then(() => {
				frappe.show_alert({ message, indicator: "green" });
				frm.reload_doc();
			});

		frm.add_custom_button(__("Recompute Balance"), () => call("recompute_balance", {}, __("Balance recomputed")), __("Actions"));
		frm.add_custom_button(__("Reissue Pass"), () =>
			frappe.confirm(__("The current barcode stops working and every wallet pass is updated. Continue?"), () =>
				call("reissue", {}, __("Barcode reissued"))
			), __("Actions"));

		const status = (target, label) =>
			frm.add_custom_button(label, () =>
				frappe.prompt({ fieldname: "remarks", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }, (v) =>
					call("change_status", { status: target, remarks: v.remarks }, __("Status: {0}", [target]))
				), __("Actions"));

		if (frm.doc.status === "Active") status("Suspended", __("Suspend"));
		if (frm.doc.status === "Suspended") status("Active", __("Reactivate"));
		if (frm.doc.status !== "Closed") status("Closed", __("Close Account"));
	},
});
