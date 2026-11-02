// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Loyalty Liability"] = {
	filters: [{ fieldname: "programme", label: __("Programme"), fieldtype: "Link", options: "ArcPOS Loyalty Programme" }],
};
