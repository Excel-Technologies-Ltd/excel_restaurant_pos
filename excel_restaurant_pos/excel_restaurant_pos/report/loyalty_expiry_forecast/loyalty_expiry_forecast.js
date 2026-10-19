// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Loyalty Expiry Forecast"] = {
	filters: [
		{ fieldname: "programme", label: __("Programme"), fieldtype: "Link", options: "ArcPOS Loyalty Programme" },
		{ fieldname: "period", label: __("Period"), fieldtype: "Select", options: "Monthly\nWeekly", default: "Monthly" },
		{ fieldname: "horizon_months", label: __("Months Ahead"), fieldtype: "Int", default: 12 },
	],
};
