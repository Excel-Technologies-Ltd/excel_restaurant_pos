// Copyright (c) 2026, Sohanur Rahman and contributors
// For license information, please see license.txt

frappe.query_reports["PnL Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "section",
			label: __("Section"),
			fieldtype: "Select",
			options: ["Both", "Income", "Expense"],
			default: "Both",
		},
		{
			fieldname: "type",
			label: __("Type"),
			fieldtype: "Link",
			options: "PnL Category",
			// filtered dynamically by on_change below
			get_query() {
				const section = frappe.query_report.get_filter_value("section");
				const filters = { is_group: 1 };
				if (section && section !== "Both") {
					filters.pnl_type = section;
				}
				return { filters };
			},
			on_change() {
				// Reset sub_type whenever type changes
				frappe.query_report.set_filter_value("sub_type", "");
			},
		},
		{
			fieldname: "sub_type",
			label: __("Sub Type"),
			fieldtype: "Link",
			options: "PnL Category",
			get_query() {
				const type = frappe.query_report.get_filter_value("type");
				return {
					filters: {
						parent_pnl_category: type || "__never__",
						is_group: 0,
					},
				};
			},
		},
	],

	// ------------------------------------------------------------------
	// Formatter — colour-code amounts and bold section headers
	// ------------------------------------------------------------------
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!data) return value;

		// Section headers (INCOME / EXPENSE) — dark background stripe
		if (data.bold && data.indent === 0 && data._section && data._section.endsWith("_header")) {
			return `<span style="font-weight:700; letter-spacing:.05em;">${value}</span>`;
		}

		// Total rows
		if (data.bold && data.indent === 0 && data._section && data._section.endsWith("_total")) {
			return `<span style="font-weight:700;">${value}</span>`;
		}

		// Net Profit / Net Loss
		if (data._section === "net" && column.fieldname === "amount") {
			const color = (data.amount || 0) >= 0 ? "#28a745" : "#dc3545";
			return `<span style="color:${color}; font-weight:700;">${value}</span>`;
		}

		// Income amounts — green tint
		if (data._section === "income" && column.fieldname === "amount" && value) {
			return `<span style="color:#28a745;">${value}</span>`;
		}

		// Expense amounts — red tint
		if (data._section === "expense" && column.fieldname === "amount" && value) {
			return `<span style="color:#dc3545;">${value}</span>`;
		}

		return value;
	},

	// ------------------------------------------------------------------
	// Toolbar button — quick date shortcuts
	// ------------------------------------------------------------------
	onload(report) {
		report.page.add_inner_button(__("This Month"), () => {
			report.set_filter_value("from_date", frappe.datetime.month_start());
			report.set_filter_value("to_date", frappe.datetime.month_end());
			report.refresh();
		});

		report.page.add_inner_button(__("This Year"), () => {
			report.set_filter_value("from_date", frappe.datetime.year_start());
			report.set_filter_value("to_date", frappe.datetime.year_end());
			report.refresh();
		});

		report.page.add_inner_button(__("Last Month"), () => {
			const today = frappe.datetime.get_today();
			const firstOfThisMonth = frappe.datetime.month_start(today);
			const lastMonth = frappe.datetime.add_days(firstOfThisMonth, -1);
			report.set_filter_value("from_date", frappe.datetime.month_start(lastMonth));
			report.set_filter_value("to_date", lastMonth);
			report.refresh();
		});
	},
};
