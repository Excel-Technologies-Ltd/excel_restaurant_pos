"""Sign in with Google, ending in the same tokens as a password login.

The storefront shows Google's sign-in button (Google Identity Services), which
hands it an ID token -- a JWT signed by Google. It posts that here as
`credential`. This verifies it and returns exactly what api.auth.login returns,
so the apps treat both sign-ins identically.

Frappe's built-in Google login is a redirect flow that ends in a session cookie,
which does not fit apps holding bearer tokens across domains; hence this.

What is checked, and why each matters:

- Signature, against Google's published keys -- anything else is forgeable.
- Audience is one of *our* client IDs. Without this, a token Google issued to
  any other website would sign someone in here.
- Issuer is Google, and the token has not expired.
- email_verified. An unverified address proves nothing about who is signing in.

Staff accounts are refused. An account with more than storefront roles is
protected by a password and possibly 2FA; letting a Google account with the
same address in would sidestep both. `google_login_allow_staff` in site_config
turns that off, deliberately.
"""

import frappe
from frappe import _
from frappe.utils import cint
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from excel_restaurant_pos.api.auth.login import issue_login_response
from excel_restaurant_pos.shared.web_customer import ensure_customer_for_user, web_customer_roles
from excel_restaurant_pos.utils.error_handler import ErrorCode, throw_error

CLIENT_IDS_CONFIG_KEY = "google_oauth_client_ids"
ALLOW_STAFF_CONFIG_KEY = "google_login_allow_staff"

GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Tolerate small clock differences between Google and this server.
CLOCK_SKEW_SECONDS = 10

# Roles every account carries automatically; they say nothing about staff.
AUTOMATIC_ROLES = {"All", "Guest", "Desk User"}


def client_ids():
	"""The OAuth client IDs whose tokens this site accepts. Empty means off."""
	configured = frappe.conf.get(CLIENT_IDS_CONFIG_KEY)
	if not configured:
		return []
	if isinstance(configured, str):
		configured = [configured]

	return [str(value).strip() for value in configured if str(value).strip()]


def _refuse(message, detail, status=401):
	frappe.log_error(title="Google sign-in refused", message=detail)
	throw_error(ErrorCode.UNAUTHORIZED, message, http_status_code=status)


def verify_credential(credential):
	"""Google's claims for a genuine token addressed to us, or a refusal."""
	audiences = client_ids()
	if not audiences:
		throw_error(ErrorCode.UNAUTHORIZED, _("Google sign-in is not enabled."), http_status_code=403)

	if not credential or not isinstance(credential, str):
		_refuse(_("Google sign-in failed. Please try again."), "no credential supplied")

	try:
		claims = google_id_token.verify_oauth2_token(
			credential,
			google_requests.Request(),
			audience=audiences,
			clock_skew_in_seconds=CLOCK_SKEW_SECONDS,
		)
	except Exception as exc:
		# Bad signature, wrong audience, expired, malformed -- or Google's keys
		# could not be fetched. None of these may sign anyone in.
		_refuse(_("Google sign-in failed. Please try again."), f"token rejected: {exc}")

	if claims.get("iss") not in GOOGLE_ISSUERS:
		_refuse(_("Google sign-in failed. Please try again."), f"issuer {claims.get('iss')!r}")

	email = (claims.get("email") or "").strip().lower()
	if not email or not claims.get("email_verified"):
		_refuse(
			_("Your Google account's email address is not verified."),
			f"email={email!r} email_verified={claims.get('email_verified')!r}",
		)

	claims["email"] = email
	return claims


def _is_staff(user):
	if user == "Administrator":
		return True

	extra = set(frappe.get_roles(user)) - set(web_customer_roles()) - AUTOMATIC_ROLES
	return bool(extra)


def _create_web_user(claims):
	"""A storefront account for a Google identity seen for the first time."""
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": claims["email"],
			"first_name": claims.get("given_name") or claims.get("name") or claims["email"],
			"last_name": claims.get("family_name") or "",
			"enabled": 1,
			"user_type": "Website User",
		}
	)
	user.flags.ignore_permissions = True
	user.flags.no_welcome_mail = True
	user.insert()
	user.add_roles(*web_customer_roles())
	return user


@frappe.whitelist(allow_guest=True, methods=["POST"])
def google_login(credential=None):
	"""Sign in with a Google ID token. Returns what api.auth.login returns."""
	frappe.set_user("Guest")

	claims = verify_credential(credential)
	email = claims["email"]

	user_name = frappe.db.get_value("User", {"email": email}, "name")
	if user_name:
		user_doc = frappe.get_doc("User", user_name)
		if not cint(user_doc.enabled):
			throw_error(
				ErrorCode.UNAUTHORIZED,
				_("User is disabled. Please contact your System Manager."),
				http_status_code=403,
			)
		if _is_staff(user_name) and not cint(frappe.conf.get(ALLOW_STAFF_CONFIG_KEY)):
			_refuse(
				_("Please sign in with your password."),
				f"staff account {user_name}: Google sign-in is for storefront accounts only",
				status=403,
			)
	else:
		user_doc = _create_web_user(claims)

	ensure_customer_for_user(user_doc)
	return issue_login_response(user_doc.name, user_doc)
