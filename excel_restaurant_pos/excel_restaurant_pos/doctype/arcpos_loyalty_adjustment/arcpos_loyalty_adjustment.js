// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

const ADJUSTMENT_API = "excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_adjustment.arcpos_loyalty_adjustment";

frappe.ui.form.on("ArcPOS Loyalty Adjustment", {
	refresh(frm) {
		const approver = frappe.user.has_role(["ArcPOS Loyalty Manager", "System Manager"]);
		if (frm.doc.docstatus !== 0 || frm.is_new() || !approver || frm.doc.approval_status === "Rejected") return;

		frm.add_custom_button(__("Approve & Post"), () =>
			frappe.call({ method: `${ADJUSTMENT_API}.approve`, args: { name: frm.doc.name } }).then(() => frm.reload_doc())
		).addClass("btn-primary");

		frm.add_custom_button(__("Reject"), () =>
			frappe.prompt({ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }, (v) =>
				frappe.call({ method: `${ADJUSTMENT_API}.reject`, args: { name: frm.doc.name, reason: v.reason } }).then(() => frm.reload_doc())
			)
		);
	},
});
