// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Loyalty Campaign Performance"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "programme", label: __("Programme"), fieldtype: "Link", options: "ArcPOS Loyalty Programme" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nDraft\nScheduled\nActive\nPaused\nEnded" },
	],
};
