// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Loyalty Points Summary"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -12) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: "Month\nWeek\nDay\nCampaign\nChannel\nType", default: "Month" },
		{ fieldname: "programme", label: __("Programme"), fieldtype: "Link", options: "ArcPOS Loyalty Programme" },
		{ fieldname: "campaign", label: __("Campaign"), fieldtype: "Link", options: "ArcPOS Loyalty Campaign" },
		{ fieldname: "channel", label: __("Channel"), fieldtype: "Select", options: "\ndine_in\nin_store_pickup\nonline_delivery\nonline_pickup\nnon_order" },
	],
};
