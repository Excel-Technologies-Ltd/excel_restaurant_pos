// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.query_reports["Gift Card Redemption History"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "gift_card",
			label: __("Gift Card"),
			fieldtype: "Link",
			options: "Coupon Code",
			get_query: () => ({
				filters: { coupon_type: "Gift Card" },
			}),
		},
		{
			fieldname: "sales_invoice",
			label: __("Sales Invoice"),
			fieldtype: "Link",
			options: "Sales Invoice",
		},
	],
};
