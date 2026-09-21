# Copyright (c) 2026, Excel and Contributors
# See license.txt

"""Every endpoint a signed-out caller can reach, on purpose.

Anything whitelisted with allow_guest=True that is not listed here fails this
test. Ordering, paying and everything staff do need an account; before this
list existed, sales reports, the till's expected cash, Meta catalog edits and
an invoice-creating hook function were all callable by anyone.

Adding an endpoint here is a decision: it is reachable with no account at all.
"""

import ast
import os

from frappe.tests.utils import FrappeTestCase

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PUBLIC = {
	# auth
	"api.auth.login.login", "api.auth.login.verify_2fa_and_login", "api.auth.token.refresh",
	"api.auth.google.google_login", "api.auth.forgot.send_forgot_password_otp",
	"api.auth.forgot.verify_forgot_password_otp", "api.auth.forgot.reset_password_with_otp",
	"api.auth.forgot.resend_forgot_password_otp",
	"overrides.user.sign_up", "overrides.user.verify_otp", "overrides.user.resend_otp",
	# storefront browsing
	"api.item.get_item_list.get_item_list", "api.item.get_item_details.get_item_details",
	"api.item_group.get_item_group_list.get_item_group_list", "api.settings.get_settings.get_settings",
	"api.settings.system_settings.system_settings", "api.territory.get_default_territory.get_default_territory",
	"api.table.get_table.get_table", "api.tips.get_tips.get_tips",
	"api.mode_of_payment.mode_of_paymet_list.get_mode_of_payment_list",
	# meta pixel (conversions API) for anonymous visitors
	*[f"api.meta.capi.track_{e}" for e in ("add_payment_info", "add_to_cart", "add_to_wishlist", "custom_event",
	  "find_location", "initiate_checkout", "purchase", "search", "view_content")],
	# emailed feedback links
	"api.feedback.get_feedback.get_feedback", "api.feedback.update_feedback.update_feedback",
	"api.file.upload_files.upload_public_file",
	# browser downloads without a bearer token
	"api.file.download_files.download_public_file", "api.timeclock.export.timeclock_export_download",
	# external callers
	"api.uber_eats.uber_eats.webhook", "api.clover.clover.webhook", "api.clover.clover.oauth_callback",
	"api.reservation.create_reservation.create_reservation", "api.reservation.create_reservation.get_available_slots",
}


def guest_endpoints():
	"""Dotted paths (without the app prefix) of every allow_guest=True function."""
	found = set()
	for root, _dirs, files in os.walk(APP_DIR):
		for name in files:
			if not name.endswith(".py") or name.startswith("test_"):
				continue
			path = os.path.join(root, name)
			with open(path) as f:
				tree = ast.parse(f.read())
			module = os.path.relpath(path[:-3], APP_DIR).replace(os.sep, ".")
			for node in ast.walk(tree):
				if not isinstance(node, ast.FunctionDef):
					continue
				for decorator in node.decorator_list:
					if isinstance(decorator, ast.Call) and any(
						k.arg == "allow_guest" and getattr(k.value, "value", False) is True
						for k in decorator.keywords
					):
						found.add(f"{module}.{node.name}")
	return found


class TestGuestEndpoints(FrappeTestCase):
	def test_only_the_intended_endpoints_are_public(self):
		found = guest_endpoints()
		self.assertEqual(found - PUBLIC, set(), "public without being listed in PUBLIC")
		self.assertEqual(PUBLIC - found, set(), "listed in PUBLIC but no longer public")
