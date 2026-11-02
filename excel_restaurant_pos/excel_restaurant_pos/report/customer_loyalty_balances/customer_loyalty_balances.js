// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Customer Loyalty Balances"] = {
	filters: [
		{ fieldname: "programme", label: __("Programme"), fieldtype: "Link", options: "ArcPOS Loyalty Programme" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nActive\nSuspended\nClosed", default: "Active" },
		{ fieldname: "tier", label: __("Tier"), fieldtype: "Data" },
		{ fieldname: "min_points", label: __("Min Available Points"), fieldtype: "Int" },
	],
};
