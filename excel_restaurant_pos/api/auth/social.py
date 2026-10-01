"""What Google and Apple sign-in do once the provider has vouched for an email.

Each provider module verifies its own token; from a verified email onwards the
two are identical, and live here so they cannot drift: the account is found or
created as a storefront account, staff are refused, and the response is exactly
what api.auth.login returns.

Staff accounts are refused unless the provider's allow-staff setting is on. An
account with more than storefront roles is protected by a password and possibly
2FA; letting a Google or Apple account with the same address in would sidestep
both. Administrator is always refused.
"""

import frappe
from frappe import _
from frappe.utils import cint

from excel_restaurant_pos.api.auth.login import issue_login_response
from excel_restaurant_pos.shared.customer_access import is_staff
from excel_restaurant_pos.shared.web_customer import ensure_customer_for_user, web_customer_roles
from excel_restaurant_pos.utils.error_handler import ErrorCode, throw_error


def _create_web_user(email, first_name, last_name):
	"""A storefront account for an identity seen for the first time."""
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name or email,
			"last_name": last_name or "",
			"enabled": 1,
			"user_type": "Website User",
		}
	)
	user.flags.ignore_permissions = True
	user.flags.no_welcome_mail = True
	user.insert()
	user.add_roles(*web_customer_roles())
	return user


def sign_in_verified_email(email, provider, allow_staff, first_name=None, last_name=None):
	"""Tokens for the account behind an email the provider has verified.

	`provider` names it in the Error Log; `first_name` and `last_name` are used
	only when the account is new.
	"""
	user_name = frappe.db.get_value("User", {"email": email}, "name")
	if user_name:
		user_doc = frappe.get_doc("User", user_name)
		if not cint(user_doc.enabled):
			throw_error(
				ErrorCode.UNAUTHORIZED,
				_("User is disabled. Please contact your System Manager."),
				http_status_code=403,
			)
		if is_staff(user_name) and not allow_staff:
			frappe.log_error(
				title=f"{provider} sign-in refused",
				message=f"staff account {user_name}: {provider} sign-in is for storefront accounts only",
			)
			throw_error(ErrorCode.UNAUTHORIZED, _("Please sign in with your password."), http_status_code=403)
	else:
		user_doc = _create_web_user(email, first_name, last_name)

	ensure_customer_for_user(user_doc)
	return issue_login_response(user_doc.name, user_doc)
