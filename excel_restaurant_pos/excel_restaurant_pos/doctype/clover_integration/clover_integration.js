// Copyright (c) 2026, Excel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Clover Integration", {
    refresh(frm) {
        // Show "Connect with Clover" button when credentials are saved but no token yet
        if (frm.doc.client_id && frm.doc.authorization_url && !frm.doc.access_token) {
            frm.add_custom_button(__("Connect with Clover"), () => {
                window.open(frm.doc.authorization_url, "_blank");
            }, __("OAuth"));
        }

        // Show "Disconnect" button when a token exists
        if (frm.doc.access_token) {
            frm.add_custom_button(__("Disconnect"), () => {
                frappe.confirm(
                    __("This will clear the stored access token and merchant ID. Continue?"),
                    () => {
                        frappe.call({
                            method: "excel_restaurant_pos.api.clover.clover.disconnect",
                            callback(r) {
                                if (!r.exc) {
                                    frappe.show_alert({ message: __("Clover disconnected"), indicator: "green" });
                                    frm.reload_doc();
                                }
                            },
                        });
                    }
                );
            }, __("OAuth"));

            frm.add_custom_button(__("Test Connection"), () => {
                frappe.call({
                    method: "excel_restaurant_pos.api.clover.clover.test_connection",
                    callback(r) {
                        if (r.message && r.message.merchant_id) {
                            frappe.show_alert({
                                message: __("Connected! Merchant: {0}", [r.message.merchant_id]),
                                indicator: "green",
                            });
                        }
                    },
                });
            }, __("OAuth"));
        }

        // Copy webhook URL helper
        if (frm.doc.webhook_url) {
            frm.add_custom_button(__("Copy Webhook URL"), () => {
                frappe.utils.copy_to_clipboard(frm.doc.webhook_url);
                frappe.show_alert({ message: __("Webhook URL copied"), indicator: "blue" });
            });
        }
    },
});
