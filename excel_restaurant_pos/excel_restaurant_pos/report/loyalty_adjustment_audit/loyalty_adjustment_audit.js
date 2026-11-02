// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Loyalty Adjustment Audit"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "approval_status", label: __("Status"), fieldtype: "Select", options: "\nDraft\nPending Approval\nApproved\nRejected" },
		{ fieldname: "reason", label: __("Reason"), fieldtype: "Select", options: "\nGoodwill\nCorrection\nPromotion\nMigration\nOther" },
		{ fieldname: "account", label: __("Member"), fieldtype: "Link", options: "ArcPOS Loyalty Account" },
	],
};
