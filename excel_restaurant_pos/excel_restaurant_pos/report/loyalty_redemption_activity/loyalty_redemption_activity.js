// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Loyalty Redemption Activity"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "channel", label: __("Channel"), fieldtype: "Select", options: "\ndine_in\nin_store_pickup\nonline_delivery\nonline_pickup" },
		{ fieldname: "territory", label: __("Outlet"), fieldtype: "Link", options: "Territory" },
		{ fieldname: "reward", label: __("Reward"), fieldtype: "Link", options: "ArcPOS Loyalty Reward" },
	],
};
