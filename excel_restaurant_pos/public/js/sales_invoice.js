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
                },
                {
                    fieldname: "discount_amount",
                    fieldtype: "Float",
                    label: __("Discount Rate"),
                    default: flt(settings.discount_rate),
                    depends_on: "eval:doc.discount_type",
                },
                {
                    fieldtype: "Column Break",
                },
                {
                    fieldname: "redemption_allow_on",
                    fieldtype: "Select",
                    label: __("Redemption Allow On"),
                    options: "\nAll\nPOS\nOnline Pickup\nOnline Delivery\nOnly Online",
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
    });
}

frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        if (frm.is_new()) {
            return;
        }

        frappe.db.get_single_value("ArcPOS Settings", "allow_auto_generate_cc").then((allowAutoGenerate) => {
            if (Number(allowAutoGenerate)) {
                return;
            }

            frappe.db.get_single_value("ArcPOS Settings", "allow_manual_generate_cc").then((allowManualGenerate) => {
                if (!Number(allowManualGenerate) || ![0, 1].includes(frm.doc.docstatus)) {
                    return;
                }

                frm.add_custom_button(__("Generate Coupon"), () => {
                    open_generate_coupon_dialog(frm);
                });
            });
        });
    },
});
