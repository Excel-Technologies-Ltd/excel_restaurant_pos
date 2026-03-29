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
			fieldname: "type",
			label: __("Type"),
			fieldtype: "Link",
			options: "PnL Category",
			get_query() {
				return { filters: { is_group: 1 } };
			},
			on_change() {
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
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
	],

	// ------------------------------------------------------------------
	// Formatter — colour-code amounts and bold section headers
	// ------------------------------------------------------------------
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!data) return value;

		const isAmount = column.fieldname === "amount";

		// Separator rows — never show $0.00
		if (data._section === "separator") {
			return isAmount ? "" : value;
		}

		// Section headers (INCOME / EXPENSE) — no amount shown
		if (data._section && data._section.endsWith("_header")) {
			if (isAmount) return "";
			return `<span style="font-weight:700; letter-spacing:.05em;">${value}</span>`;
		}

		// Total rows — no color on the label, bold on amount
		if (data._section && data._section.endsWith("_total")) {
			if (!isAmount) return `<span style="font-weight:700;">${value}</span>`;
			const isIncome = data._section === "income_total";
			const color = isIncome ? "#1a6b2f" : "#8b1a1a";
			return `<span style="color:${color}; font-weight:700;">${value}</span>`;
		}

		// Net Profit / Net Loss
		if (data._section === "net" && isAmount) {
			const color = (data.amount || 0) >= 0 ? "#28a745" : "#dc3545";
			return `<span style="color:${color}; font-weight:700;">${value}</span>`;
		}

		// Net Profit / Net Loss — bold label
		if (data._section === "net" && column.fieldname === "particulars" && value) {
			const color = (data.amount || 0) >= 0 ? "#28a745" : "#dc3545";
			return `<span style="color:${color}; font-weight:700;">${value}</span>`;
		}

		// Type, Sub Type & Particulars columns — bold on type (indent 1) and sub-type (indent 2) group rows
		if ((column.fieldname === "category_type" || column.fieldname === "category_sub_type" || column.fieldname === "particulars") && value) {
			const weight = (data.bold && (data.indent === 1 || data.indent === 2)) ? "700" : "400";
			return `<span style="font-weight:${weight};">${value}</span>`;
		}

		// Income amounts — multi-level green shades #51a451ff
		if (data._section === "income" && isAmount && value) {
			// indent 1 = type group (dark), indent 2 = sub-type (medium), indent 3 = leaf (light)
			const color = data.indent === 1 ? "#1a6b2f"
				: data.indent === 2 ? "#28a745"
				: "#1a6b2f"; 
			const weight = data.bold ? "700" : "400";
			return `<span style="color:${color}; font-weight:${weight};">${value}</span>`;
		}

		// Expense amounts — multi-level red shades
		if (data._section === "expense" && isAmount && value) {
			const color = data.indent === 1 ? "#8b1a1a"
				: data.indent === 2 ? "#c0392b"
				: "#8b1a1a";
			const weight = data.bold ? "700" : "400";
			return `<span style="color:${color}; font-weight:${weight};">${value}</span>`;
		}

		return value;
	},

	// ------------------------------------------------------------------
	// Toolbar button — quick date shortcuts
	// ------------------------------------------------------------------
	onload(report) {
		// Bold & larger summary tile values
		if (!document.getElementById("pnl-summary-style")) {
			const style = document.createElement("style");
			style.id = "pnl-summary-style";
			style.textContent = `
				.report-summary .summary-value {
					font-weight: 700 !important;
					font-size: 1.4rem !important;
				}
				.report-summary .summary-label {
					font-weight: 600 !important;
					font-size: 0.85rem !important;
					letter-spacing: 0.03em;
				}
			`;
			document.head.appendChild(style);
		}

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

		
	},
};
