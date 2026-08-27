// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Gift Card Outstanding Liability"] = {
	filters: [
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nActive\nInactive\nUsed\nExpired\nRejected",
			default: "Active",
		},
		{
			fieldname: "email",
			label: __("Email contains"),
			fieldtype: "Data",
		},
	],
};
