# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CloverIntegration(Document):
    def before_save(self):
        """Recompute the authorization URL and webhook URL whenever the doc is saved."""
        env = self.environment or "Sandbox"
        base = "https://sandbox.dev.clover.com" if env == "Sandbox" else "https://www.clover.com"
        site_url = frappe.utils.get_url()

        if self.client_id:
            redirect = self.redirect_uri or f"{site_url}/api/method/excel_restaurant_pos.api.clover.clover.oauth_callback"
            self.redirect_uri = redirect
            self.authorization_url = (
                f"{base}/oauth/authorize"
                f"?client_id={self.client_id}"
                f"&redirect_uri={redirect}"
            )

        self.webhook_url = f"{site_url}/api/method/excel_restaurant_pos.api.clover.clover.webhook"
