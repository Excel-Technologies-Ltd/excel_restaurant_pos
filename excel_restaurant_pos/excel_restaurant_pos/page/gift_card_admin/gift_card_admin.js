frappe.pages["gift-card-admin"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Gift Card Admin"),
		single_column: true,
	});

	frappe.gift_card_admin = new GiftCardAdmin(page);
};

class GiftCardAdmin {
	constructor(page) {
		this.page = page;
		this.offset = 0;
		this.limit = 50;
		this.setup_actions();
		this.setup_filters();
		this.setup_body();
		this.refresh();
	}

	setup_actions() {
		this.page.set_primary_action(__("Bulk Create"), () => this.open_bulk_dialog());
		this.page.add_inner_button(__("Import CSV"), () => this.open_import_dialog());
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.page.add_inner_button(__("Outstanding Liability"), () => {
			frappe.set_route("query-report", "Gift Card Outstanding Liability");
		});
		this.page.add_inner_button(__("Redemption History"), () => {
			frappe.set_route("query-report", "Gift Card Redemption History");
		});
	}

	setup_filters() {
		this.status_field = this.page.add_field({
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nInactive\nActive\nUsed\nExpired\nRejected",
			change: () => {
				this.offset = 0;
				this.refresh();
			},
		});
		this.search_field = this.page.add_field({
			fieldname: "search",
			label: __("Search"),
			fieldtype: "Data",
			change: frappe.utils.debounce(() => {
				this.offset = 0;
				this.refresh();
			}, 400),
		});
	}

	setup_body() {
		this.$summary = $(`<div class="gift-card-admin-summary mb-3"></div>`).appendTo(
			this.page.body
		);
		this.$table_wrap = $(`<div class="gift-card-admin-table"></div>`).appendTo(this.page.body);
		this.$pager = $(
			`<div class="gift-card-admin-pager flex justify-between mt-3"></div>`
		).appendTo(this.page.body);
	}

	refresh() {
		const status = this.status_field.get_value();
		const search = this.search_field.get_value();

		frappe.call({
			method: "api.gift_cards.list",
			args: {
				status: status || undefined,
				search: search || undefined,
				limit: this.limit,
				offset: this.offset,
			},
			freeze: true,
			callback: (r) => {
				const msg = r.message || {};
				this.render_table(msg.data || [], msg.total || 0);
			},
		});
	}

	render_table(rows, total) {
		const currency = (v) => format_currency(flt(v));
		let html = `
			<table class="table table-bordered table-hover">
				<thead>
					<tr>
						<th>${__("Code")}</th>
						<th>${__("Status")}</th>
						<th>${__("Face Value")}</th>
						<th>${__("Balance")}</th>
						<th>${__("Email")}</th>
						<th>${__("Sold On")}</th>
						<th>${__("Valid Upto")}</th>
					</tr>
				</thead>
				<tbody>
		`;

		if (!rows.length) {
			html += `<tr><td colspan="7" class="text-muted text-center">${__(
				"No gift cards found"
			)}</td></tr>`;
		} else {
			rows.forEach((row) => {
				html += `
					<tr>
						<td><a href="/app/coupon-code/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(
					row.coupon_code || row.name
				)}</a></td>
						<td>${frappe.utils.escape_html(row.custom_status || "")}</td>
						<td>${currency(row.custom_discount_amount)}</td>
						<td>${currency(row.custom_available_balance)}</td>
						<td>${frappe.utils.escape_html(row.custom_linked_email || "")}</td>
						<td>${
							row.custom_generated_on_order
								? `<a href="/app/sales-invoice/${encodeURIComponent(
										row.custom_generated_on_order
								  )}">${frappe.utils.escape_html(row.custom_generated_on_order)}</a>`
								: ""
						}</td>
						<td>${row.valid_upto || ""}</td>
					</tr>
				`;
			});
		}

		html += `</tbody></table>`;
		this.$table_wrap.html(html);
		this.$summary.html(
			`<p class="text-muted">${__("Showing")} ${rows.length} ${__("of")} ${total}</p>`
		);

		this.$pager.empty();
		const $prev = $(`<button class="btn btn-default btn-sm">${__("Previous")}</button>`);
		const $next = $(`<button class="btn btn-default btn-sm">${__("Next")}</button>`);
		$prev.prop("disabled", this.offset <= 0);
		$next.prop("disabled", this.offset + this.limit >= total);
		$prev.on("click", () => {
			this.offset = Math.max(0, this.offset - this.limit);
			this.refresh();
		});
		$next.on("click", () => {
			this.offset += this.limit;
			this.refresh();
		});
		this.$pager.append($prev).append($next);
	}

	open_bulk_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Bulk Create Inactive Gift Cards"),
			fields: [
				{
					fieldname: "qty",
					fieldtype: "Int",
					label: __("Quantity"),
					reqd: 1,
					default: 10,
					description: __("Max 500"),
				},
				{
					fieldname: "amount",
					fieldtype: "Currency",
					label: __("Face Value"),
					reqd: 1,
				},
				{
					fieldname: "prefix",
					fieldtype: "Data",
					label: __("Code Prefix Override"),
					description: __("Optional. Defaults to ArcPOS Settings gift_card_prefix."),
				},
				{
					fieldname: "linked_email",
					fieldtype: "Data",
					label: __("Linked Email (optional)"),
				},
			],
			primary_action_label: __("Create"),
			primary_action: (values) => {
				frappe.call({
					method: "api.gift_cards.generate_bulk",
					args: values,
					freeze: true,
					freeze_message: __("Creating gift cards..."),
					callback: (r) => {
						const msg = r.message || {};
						frappe.show_alert({
							message: __("Created {0} gift cards", [msg.created_count || 0]),
							indicator: "green",
						});
						dialog.hide();
						this.offset = 0;
						this.status_field.set_value("Inactive");
						this.refresh();
						if ((msg.codes || []).length) {
							frappe.msgprint({
								title: __("Created Codes"),
								message: `<pre style="max-height:240px;overflow:auto">${frappe.utils.escape_html(
									(msg.codes || []).join("\n")
								)}</pre>`,
								indicator: "green",
							});
						}
					},
				});
			},
		});
		dialog.show();
	}

	open_import_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Import Inactive Gift Cards (CSV)"),
			fields: [
				{
					fieldname: "help",
					fieldtype: "HTML",
					options: `<p class="text-muted">${__(
						"Headers: code (optional), amount, email (optional). One row per card."
					)}</p>
					<pre>code,amount,email
GIFT-001,1000,guest@example.com
,2000,</pre>`,
				},
				{
					fieldname: "csv_text",
					fieldtype: "Code",
					label: __("CSV"),
					reqd: 1,
					options: "CSV",
				},
			],
			primary_action_label: __("Import"),
			primary_action: (values) => {
				frappe.call({
					method: "api.gift_cards.import",
					args: { csv_text: values.csv_text },
					freeze: true,
					freeze_message: __("Importing..."),
					callback: (r) => {
						const msg = r.message || {};
						frappe.show_alert({
							message: __("Imported {0} (errors: {1})", [
								msg.created_count || 0,
								msg.error_count || 0,
							]),
							indicator: msg.error_count ? "orange" : "green",
						});
						dialog.hide();
						this.offset = 0;
						this.status_field.set_value("Inactive");
						this.refresh();
						if (msg.errors && msg.errors.length) {
							frappe.msgprint({
								title: __("Import Errors"),
								message: `<pre>${frappe.utils.escape_html(
									msg.errors
										.map((e) => `Row ${e.row}: ${e.message}`)
										.join("\n")
								)}</pre>`,
								indicator: "orange",
							});
						}
					},
				});
			},
		});
		dialog.show();
	}
}
