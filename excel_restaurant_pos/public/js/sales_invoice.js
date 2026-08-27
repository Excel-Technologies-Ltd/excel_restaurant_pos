const COUPON_BUTTON_GROUP = __("Coupon");
const COUPON_BUTTON_LABEL = __("Generate Coupon");
const GIFT_CARD_BUTTON_GROUP = __("Gift Card");

function open_generate_coupon_dialog(frm) {
    frappe.db.get_doc("ArcPOS Settings", "ArcPOS Settings").then((settings) => {
        const linked_email = frm.doc.custom_coupon_for || frm.doc.custom_email_address || "";

        const dialog = new frappe.ui.Dialog({
            title: __("Generate Coupon"),
            fields: [
                {
                    fieldtype: "Section Break",
                    label: __("Validity"),
                },
                {
                    fieldname: "expire_after_days",
                    fieldtype: "Int",
                    label: __("Expire After (Days)"),
                    default: cint(settings.expire_after_days),
                    description: __("Used when Valid Upto is empty."),
                },
                {
                    fieldname: "valid_upto",
                    fieldtype: "Date",
                    label: __("Valid Upto"),
                    description: __("Optional. Overrides Expire After (Days)."),
                },
                {
                    fieldtype: "Column Break",
                },
                {
                    fieldname: "max_use",
                    fieldtype: "Int",
                    label: __("Max Use"),
                    default: cint(settings.max_use) || 1,
                },
                {
                    fieldname: "minimum_subtotal",
                    fieldtype: "Currency",
                    label: __("Minimum Subtotal (Redeem)"),
                    default: flt(settings.minimum_subtotal_redeem),
                },
                {
                    fieldtype: "Section Break",
                    label: __("Discount"),
                },
                {
                    fieldname: "discount_type",
                    fieldtype: "Select",
                    label: __("Discount Type"),
                    options: "\nPercentage\nFlat Amount",
                    default: settings.discount_type || "",
                    onchange() {
                        const is_percentage = dialog.get_value("discount_type") === "Percentage";
                        dialog.set_df_property(
                            "disc_upto_amount",
                            "hidden",
                            !is_percentage
                        );
                        if (!is_percentage) {
                            dialog.set_value("disc_upto_amount", 0);
                        }
                    },
                },
                {
                    fieldname: "discount_amount",
                    fieldtype: "Float",
                    label: __("Discount Rate"),
                    default: flt(settings.discount_rate),
                    depends_on: "eval:doc.discount_type",
                },
                {
                    fieldname: "disc_upto_amount",
                    fieldtype: "Currency",
                    label: __("Disc. Upto (Amount)"),
                    default: flt(settings.disc_upto_amount),
                    description: __("Maximum discount cap. 0 means no limit."),
                    depends_on: "eval:doc.discount_type==='Percentage'",
                },
                {
                    fieldtype: "Column Break",
                },
                {
                    fieldname: "redemption_allow_on",
                    fieldtype: "Select",
                    label: __("Redemption Allow On"),
                    options: "\nAll\nDine-in\nIn Store Pickup\nPOS\nOnline Pickup\nOnline Delivery\nOnly Online",
                    default: settings.cc_allow_on_redeem || "",
                },
                {
                    fieldname: "linked_email",
                    fieldtype: "Data",
                    label: __("Linked Email"),
                    options: "Email",
                    default: linked_email,
                },
                {
                    fieldtype: "Section Break",
                },
                {
                    fieldname: "description",
                    fieldtype: "Small Text",
                    label: __("Coupon Description"),
                },
            ],
            primary_action_label: __("Generate"),
            primary_action(values) {
                if (!values.valid_upto && !cint(values.expire_after_days)) {
                    frappe.msgprint({
                        title: __("Missing Validity"),
                        message: __("Set Expire After (Days) or Valid Upto before generating the coupon."),
                        indicator: "orange",
                    });
                    return;
                }

                const args = {
                    sales_invoice: frm.doc.name,
                };

                const optional_fields = {
                    expire_after_days: values.expire_after_days,
                    valid_upto: values.valid_upto,
                    max_use: values.max_use,
                    minimum_subtotal: values.minimum_subtotal,
                    discount_type: values.discount_type,
                    discount_amount: values.discount_amount,
                    disc_upto_amount:
                        values.discount_type === "Percentage" ? values.disc_upto_amount : undefined,
                    redemption_allow_on: values.redemption_allow_on,
                    linked_email: values.linked_email,
                    description: values.description,
                };

                Object.entries(optional_fields).forEach(([fieldname, value]) => {
                    if (value !== undefined && value !== null && value !== "") {
                        args[fieldname] = value;
                    }
                });

                dialog.hide();

                frappe.call({
                    method: "api.coupons.generate",
                    args,
                    freeze: true,
                    freeze_message: __("Generating coupon..."),
                    callback(r) {
                        if (r.exc) {
                            return;
                        }

                        const couponCode = r.message?.coupon_code || "";
                        const validUpto = r.message?.valid_upto || "";
                        const message = validUpto
                            ? __("Coupon generated: {0} (valid upto {1})", [couponCode, validUpto])
                            : __("Coupon generated: {0}", [couponCode]);

                        frappe.show_alert(
                            {
                                message,
                                indicator: "green",
                            },
                            7
                        );
                        frm.reload_doc();
                    },
                });
            },
        });

        dialog.show();
        dialog.fields_dict.discount_type.df.onchange();
    });
}

function should_show_generate_coupon_button(frm, settings) {
    if (frm.is_new()) {
        return false;
    }
    if (!cint(settings.allow_manual_generate_cc)) {
        return false;
    }
    if (![0, 1].includes(frm.doc.docstatus)) {
        return false;
    }
    if (frm.doc.custom_generated_coupon_code) {
        return false;
    }
    return true;
}

function setup_generate_coupon_button(frm) {
    frm._coupon_button_request_id = (frm._coupon_button_request_id || 0) + 1;
    const request_id = frm._coupon_button_request_id;

    frappe.db.get_doc("ArcPOS Settings", "ArcPOS Settings").then((settings) => {
        if (request_id !== frm._coupon_button_request_id) {
            return;
        }

        if (!should_show_generate_coupon_button(frm, settings)) {
            return;
        }

        frm.add_custom_button(
            COUPON_BUTTON_LABEL,
            () => open_generate_coupon_dialog(frm),
            COUPON_BUTTON_GROUP
        );
    });
}

function sync_gift_amount_from_item(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!cint(row.custom_is_gift_card_item)) {
        return;
    }

    const gift_type = (row.custom_gift_card_type || "").trim();
    if (gift_type === "Existing" && row.custom_gift_card_code) {
        frappe.db
            .get_value("Coupon Code", row.custom_gift_card_code, "custom_discount_amount")
            .then((r) => {
                const amount = flt(r.message?.custom_discount_amount);
                frappe.model.set_value(cdt, cdn, "custom_coupon_value", amount);
                frappe.model.set_value(cdt, cdn, "custom_gift_amount", amount);
            });
        return;
    }

    if (gift_type === "New" && row.item_code) {
        frappe.db.get_value("Item", row.item_code, "custom_gift_card_value").then((r) => {
            const amount = flt(r.message?.custom_gift_card_value);
            frappe.model.set_value(cdt, cdn, "custom_gift_amount", amount);
        });
    }
}

function filter_existing_gift_card_query(frm) {
    frm.set_query("custom_gift_card_code", "items", () => ({
        filters: {
            coupon_type: "Gift Card",
            custom_status: "Inactive",
        },
    }));
}

function open_apply_gift_card_dialog(frm) {
    if (frm.is_new() || cint(frm.doc.docstatus) !== 0) {
        frappe.msgprint(__("Gift cards can only be applied on a saved draft Sales Invoice."));
        return;
    }

    if ((frm.doc.custom_coupon_code || "").trim()) {
        frappe.msgprint(__("Remove the promotional coupon before applying gift cards."));
        return;
    }

    const dialog = new frappe.ui.Dialog({
        title: __("Apply Gift Card"),
        fields: [
            {
                fieldname: "gift_card_code",
                fieldtype: "Small Text",
                label: __("Gift Card Code(s)"),
                reqd: 1,
                description: __(
                    "One code, or multiple separated by comma / new line. Applied in order until the invoice is covered."
                ),
            },
            {
                fieldname: "preview_html",
                fieldtype: "HTML",
            },
        ],
        primary_action_label: __("Apply"),
        primary_action(values) {
            const code = (values.gift_card_code || "").trim();
            if (!code) {
                return;
            }
            frappe.call({
                method: "api.gift_cards.apply",
                args: {
                    sales_invoice: frm.doc.name,
                    gift_card_code: code,
                },
                freeze: true,
                freeze_message: __("Applying gift card..."),
                callback(r) {
                    if (r.exc) {
                        return;
                    }
                    const m = r.message || {};
                    const newly = m.newly_applied || [];
                    const msg = newly.length
                        ? __("Applied {0} gift card(s); discount {1}", [
                              newly.length,
                              format_currency(m.invoice_discount_amount || m.redeemed_amount || 0),
                          ])
                        : __("Applied {0}: {1}", [
                              m.gift_card_code || code,
                              format_currency(m.redeemed_amount || 0),
                          ]);
                    frappe.show_alert({ message: msg, indicator: "green" }, 7);
                    if ((m.skipped || []).length) {
                        frappe.show_alert(
                            {
                                message: __("{0} code(s) skipped (invoice already covered)", [
                                    m.skipped.length,
                                ]),
                                indicator: "orange",
                            },
                            5
                        );
                    }
                    dialog.hide();
                    frm.reload_doc();
                },
            });
        },
        secondary_action_label: __("Verify"),
        secondary_action() {
            const code = (dialog.get_value("gift_card_code") || "").trim();
            if (!code) {
                frappe.msgprint(__("Enter a gift card code first."));
                return;
            }
            const first = code
                .split(/[\n,;]/)
                .map((c) => c.trim())
                .filter(Boolean)[0];
            frappe.call({
                method: "api.gift_cards.verify",
                args: {
                    sales_invoice: frm.doc.name,
                    gift_card_code: first,
                },
                callback(r) {
                    if (r.exc || !r.message) {
                        return;
                    }
                    const m = r.message;
                    dialog.fields_dict.preview_html.$wrapper.html(`
						<div class="text-muted" style="margin-top:8px">
							<div><b>${__("First code preview")}:</b> ${frappe.utils.escape_html(first || "")}</div>
							<div><b>${__("Available Balance")}:</b> ${format_currency(m.available_balance || 0)}</div>
							<div><b>${__("Will Redeem")}:</b> ${format_currency(m.redeemed_amount || 0)}</div>
							<div><b>${__("Remaining Due After")}:</b> ${format_currency(
								flt(m.remaining_invoice_due) - flt(m.redeemed_amount)
							)}</div>
						</div>
					`);
                },
            });
        },
    });

    dialog.show();
    // Prefer barcode scanners that type into the focused field then Enter
    dialog.$wrapper.find('[data-fieldname="gift_card_code"]').find("textarea, input").focus();
}

function open_discard_gift_cards_dialog(frm) {
    const rows = frm.doc.custom_applied_gift_cards || [];
    if (!rows.length) {
        frappe.msgprint(__("No gift cards are applied on this invoice."));
        return;
    }

    const options = ["", __("All")].concat(
        rows.map((r) => r.gift_card_code).filter(Boolean)
    );

    const dialog = new frappe.ui.Dialog({
        title: __("Remove Gift Card"),
        fields: [
            {
                fieldname: "gift_card_code",
                fieldtype: "Select",
                label: __("Gift Card"),
                options: options.join("\n"),
                reqd: 1,
                description: __("Choose one code, or All to clear every applied gift card."),
            },
        ],
        primary_action_label: __("Remove"),
        primary_action(values) {
            const selected = (values.gift_card_code || "").trim();
            const args = { sales_invoice: frm.doc.name };
            if (selected && selected !== __("All")) {
                args.gift_card_code = selected;
            }
            frappe.call({
                method: "api.gift_cards.discard",
                args,
                freeze: true,
                callback(r) {
                    if (r.exc) {
                        return;
                    }
                    dialog.hide();
                    frm.reload_doc();
                },
            });
        },
    });
    dialog.show();
}

function setup_gift_card_buttons(frm) {
    if (frm.is_new() || cint(frm.doc.docstatus) !== 0) {
        return;
    }

    frm.add_custom_button(
        __("Apply Gift Card"),
        () => open_apply_gift_card_dialog(frm),
        GIFT_CARD_BUTTON_GROUP
    );

    if ((frm.doc.custom_applied_gift_cards || []).length) {
        frm.add_custom_button(
            __("Remove Gift Card"),
            () => open_discard_gift_cards_dialog(frm),
            GIFT_CARD_BUTTON_GROUP
        );
    }
}

function show_generated_gift_cards_alert(frm) {
    const codes = (frm.doc.custom_generated_gift_cards || "").trim();
    if (!codes || cint(frm.doc.docstatus) !== 1) {
        return;
    }

    frm.dashboard.add_comment(
        __("Generated Gift Cards: {0}", [frappe.utils.escape_html(codes)]),
        "blue",
        true
    );
}

function ensure_gift_cards_for_email(frm) {
    if ((frm.doc.custom_gift_cards_for || "").trim()) {
        return;
    }
    const fallback =
        (frm.doc.custom_email_address || "").trim() ||
        (frm.doc.contact_email || "").trim();
    if (fallback) {
        frm.set_value("custom_gift_cards_for", fallback);
    }
}

frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        setup_generate_coupon_button(frm);
        filter_existing_gift_card_query(frm);
        setup_gift_card_buttons(frm);
        show_generated_gift_cards_alert(frm);
    },
    custom_email_address(frm) {
        ensure_gift_cards_for_email(frm);
    },
});

frappe.ui.form.on("Sales Invoice Item", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) {
            return;
        }
        frappe.db
            .get_value("Item", row.item_code, ["custom_is_gift_card_item", "custom_gift_card_value"])
            .then((r) => {
                const is_gift = cint(r.message?.custom_is_gift_card_item);
                frappe.model.set_value(cdt, cdn, "custom_is_gift_card_item", is_gift);
                if (is_gift) {
                    if (!(row.custom_gift_card_type || "").trim()) {
                        frappe.model.set_value(cdt, cdn, "custom_gift_card_type", "New");
                    }
                    sync_gift_amount_from_item(cdt, cdn);
                    ensure_gift_cards_for_email(frm);
                }
            });
    },
    custom_gift_card_type(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if ((row.custom_gift_card_type || "").trim() === "New") {
            frappe.model.set_value(cdt, cdn, "custom_gift_card_code", "");
            frappe.model.set_value(cdt, cdn, "custom_coupon_value", "");
        }
        sync_gift_amount_from_item(cdt, cdn);
    },
    custom_gift_card_code(frm, cdt, cdn) {
        sync_gift_amount_from_item(cdt, cdn);
    },
});
