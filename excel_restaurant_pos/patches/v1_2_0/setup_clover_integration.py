"""Seed initial Clover Integration credentials (sandbox / testing).

These credentials will be replaced via the Clover Integration doctype UI
once the production app is registered. The client_secret is stored using
Frappe's Password field (encrypted at rest).
"""

import frappe


def execute():
    if not frappe.db.exists("DocType", "Clover Integration"):
        return

    doc = frappe.get_single("Clover Integration")

    # Only seed if not already configured
    if not doc.client_id:
        doc.enabled = 1
        doc.environment = "Sandbox"
        doc.client_id = "CNDWS1XF8025G"
        doc.client_secret = "bfb3555d-26cd-a4a2-ac6d-039de9906d9c"

        site_url = frappe.utils.get_url()
        doc.redirect_uri = (
            f"{site_url}/api/method/excel_restaurant_pos.api.clover.clover.oauth_callback"
        )
        doc.webhook_url = (
            f"{site_url}/api/method/excel_restaurant_pos.api.clover.clover.webhook"
        )
        doc.authorization_url = (
            f"https://sandbox.dev.clover.com/oauth/authorize"
            f"?client_id={doc.client_id}&redirect_uri={doc.redirect_uri}"
        )

        doc.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.logger().info("Clover Integration seeded with sandbox credentials")
