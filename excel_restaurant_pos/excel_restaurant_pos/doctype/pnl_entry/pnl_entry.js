// Copyright (c) 2026, Sohanur Rahman and contributors
// For license information, please see license.txt

frappe.ui.form.on("PnL Entry", {
	setup(frm) {
		// --- Income Items: filter Type to Income group categories only ---
		frm.set_query("type", "income_items", () => ({
			filters: {
				pnl_type: "Income",
				is_group: 1,
			},
		}));

		// --- Income Items: filter Sub Type based on selected Type ---
		frm.set_query("sub_type", "income_items", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				filters: {
					parent_pnl_category: row.type || "__never__",
					is_group: 0,
					pnl_type: "Income",
				},
			};
		});

		// --- Expense Items: filter Type to Expense group categories only ---
		frm.set_query("type", "expense_items", () => ({
			filters: {
				pnl_type: "Expense",
				is_group: 1,
			},
		}));

		// --- Expense Items: filter Sub Type based on selected Type ---
		frm.set_query("sub_type", "expense_items", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				filters: {
					parent_pnl_category: row.type || "__never__",
					is_group: 0,
					pnl_type: "Expense",
				},
			};
		});
	},

	refresh(frm) {
		_update_summary_colors(frm);
	},
});

// ------------------------------------------------------------------
// Income Items child table events
// ------------------------------------------------------------------
frappe.ui.form.on("PnL Income Item", {
	type(frm, cdt, cdn) {
		// Clear sub_type when type changes
		frappe.model.set_value(cdt, cdn, "sub_type", "");
	},
	amount(frm) {
		_calculate_totals(frm);
	},
	income_items_remove(frm) {
		_calculate_totals(frm);
	},
});

// ------------------------------------------------------------------
// Expense Items child table events
// ------------------------------------------------------------------
frappe.ui.form.on("PnL Expense Item", {
	type(frm, cdt, cdn) {
		// Clear sub_type when type changes
		frappe.model.set_value(cdt, cdn, "sub_type", "");
	},
	amount(frm) {
		_calculate_totals(frm);
	},
	expense_items_remove(frm) {
		_calculate_totals(frm);
	},
});

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------
function _calculate_totals(frm) {
	let total_income = 0;
	(frm.doc.income_items || []).forEach((row) => {
		total_income += row.amount || 0;
	});

	let total_expense = 0;
	(frm.doc.expense_items || []).forEach((row) => {
		total_expense += row.amount || 0;
	});

	frappe.model.set_value(frm.doctype, frm.docname, "total_income", total_income);
	frappe.model.set_value(frm.doctype, frm.docname, "total_expense", total_expense);
	frappe.model.set_value(
		frm.doctype,
		frm.docname,
		"net_profit_loss",
		total_income - total_expense
	);

	_update_summary_colors(frm);
}

function _update_summary_colors(frm) {
	const income = frm.doc.total_income || 0;
	const expense = frm.doc.total_expense || 0;
	const net = frm.doc.net_profit_loss || 0;

	let label, color;
	if (income > expense) {
		label = "Net Profit";
		color = "green";
	} else if (expense > income) {
		label = "Net Loss";
		color = "red";
	} else {
		label = "Net Profit / Loss";
		color = "grey";
	}

	frm.get_field("net_profit_loss").set_label(__(label));

	const $net_field = frm.get_field("net_profit_loss").$wrapper;
	if ($net_field) {
		$net_field.find(".control-value").css("color", color);
	}
}
