# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


CREDENTIAL_FIELDS = ("client_id", "client_secret", "api_token", "merchant_id")


class CloverIntegration(Document):
    def before_save(self):
        """Recompute URLs and clear stale OAuth token when credentials change."""
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

        # Clear OAuth access token if any credential field changed
        if not self.is_new():
            old = self.get_doc_before_save()
            if old and any(
                self.get(f) != old.get(f) for f in CREDENTIAL_FIELDS
            ):
                self.access_token = ""
                self.token_expiry = None

    def on_update(self):
        """Clear token cache after any credential change."""
        from excel_restaurant_pos.api.clover.clover_api import clear_token_cache
        clear_token_cache()
