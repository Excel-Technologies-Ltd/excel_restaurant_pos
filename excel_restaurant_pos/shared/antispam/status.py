"""One command that reports every order and payment guard on a site.

	bench --site <site> execute excel_restaurant_pos.shared.antispam.status.report

`bench execute` prints only truthy results, so asking the individual helpers
("is Turnstile on?") prints nothing at all when the answer is no. This always
returns a populated dict. It reports whether the Turnstile secret is set, never
its value.
"""

import frappe
from frappe.utils import cint, get_system_timezone

from excel_restaurant_pos.api.auth import google
from excel_restaurant_pos.api.payment_entry.create_payment import allowed_roles
from excel_restaurant_pos.api.payments.helper.claim_ticket import claims_supported
from excel_restaurant_pos.shared.antispam import turnstile
from excel_restaurant_pos.shared.sales_invoice import idempotency


def report():
	conf = frappe.conf
	return {
		"turnstile": {
			"enabled": turnstile.configured(),
			"secret_set": bool(conf.get(turnstile.SECRET_CONFIG_KEY)),
			"kill_switch_on": bool(cint(conf.get(turnstile.DISABLE_CONFIG_KEY))),
			"action": conf.get(turnstile.ACTION_CONFIG_KEY) or "(not pinned)",
			"hostnames": turnstile._allowed_hostnames() or "(not pinned)",
		},
		"honeypot_enabled": not cint(conf.get("arcpos_disable_order_honeypot")),
		"google_sign_in": {
			"enabled": bool(google.client_ids()),
			"client_ids": len(google.client_ids()),
			"staff_allowed": bool(cint(conf.get(google.ALLOW_STAFF_CONFIG_KEY))),
			"web_customer_defaults": conf.get("arcpos_web_customer_defaults") or "(none)",
		},
		"migrated": {
			"idempotency_column": idempotency.supported(),
			"ticket_claim_columns": claims_supported(),
		},
		"payment_entry_roles": sorted(allowed_roles()),
		"server_time_zone": get_system_timezone(),
	}
