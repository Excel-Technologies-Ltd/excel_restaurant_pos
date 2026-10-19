// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

const CAMPAIGN_API = "excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_campaign.arcpos_loyalty_campaign";

frappe.ui.form.on("ArcPOS Loyalty Campaign", {
	refresh(frm) {
		if (frm.is_new()) return;

		const action = (name, label) =>
			frm.add_custom_button(label, () =>
				frappe.call({ method: `${CAMPAIGN_API}.campaign_action`, args: { name: frm.doc.name, action: name } }).then((r) => {
					frappe.show_alert({ message: __("Campaign is now {0}", [r.message]), indicator: "green" });
					frm.reload_doc();
				}), __("Status"));

		if (frm.doc.status === "Draft") action("activate", __("Activate"));
		if (["Active", "Scheduled"].includes(frm.doc.status)) action("pause", __("Pause"));
		if (frm.doc.status === "Paused") action("resume", __("Resume"));
		if (frm.doc.status !== "Ended") action("end", __("End"));

		frm.add_custom_button(__("Duplicate"), () =>
			frappe.call({ method: `${CAMPAIGN_API}.duplicate_campaign`, args: { name: frm.doc.name } }).then((r) =>
				frappe.set_route("Form", "ArcPOS Loyalty Campaign", r.message)
			));

		frm.add_custom_button(__("Simulate on Order…"), () =>
			frappe.prompt(
				{ fieldname: "invoice", fieldtype: "Link", options: "Sales Invoice", label: __("Order"), reqd: 1 },
				(v) =>
					frappe.call({ method: `${CAMPAIGN_API}.simulate_campaign`, args: { name: frm.doc.name, invoice: v.invoice } }).then((r) => {
						const res = r.message || {};
						const rows = (res.awards || [])
							.map((a) => `<tr><td>${frappe.utils.escape_html(a.rule_name || a.rule_id)}</td><td>${a.campaign || __("Base")}</td><td class="text-right">${a.points}</td></tr>`)
							.join("");
						frappe.msgprint({
							title: __("Simulation: {0} points", [res.points || 0]),
							message: res.eligible === false
								? __("This order is not eligible ({0}).", [res.reason || __("programme or customer")])
								: `<table class="table table-bordered"><tr><th>${__("Rule")}</th><th>${__("Scope")}</th><th class="text-right">${__("Points")}</th></tr>${rows}</table>`,
						});
					}),
				__("Simulate"),
				__("Run")
			));
	},
});
