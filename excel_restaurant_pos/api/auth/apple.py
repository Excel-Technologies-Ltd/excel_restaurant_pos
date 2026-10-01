"""Sign in with Apple, ending in the same tokens as a password login.

The storefront (Sign in with Apple JS) and the iOS app (AuthenticationServices)
both receive an identity token -- a JWT signed by Apple. They post it here as
`credential`. This verifies it and returns exactly what api.auth.login returns,
as Google sign-in does.

What is checked, and why each matters:

- Signature, RS256 only, against Apple's published keys -- anything else is
  forgeable, and taking the algorithm from the token would let it choose.
- Audience is one of *our* client IDs: the Services ID the website uses and the
  iOS app's bundle ID. Without this, a token Apple issued to any other app
  would sign someone in here.
- Issuer is Apple, and the token has not expired.
- email_verified. Apple sends it as a string ("true") or a boolean.

Apple puts no name in the token. It gives the client the user's name once, on
the very first authorization, so the client passes it as `first_name` and
`last_name`; they are used only when the account is created. "Hide My Email"
gives a stable @privaterelay.appleid.com address, which becomes the account's
email like any other.

Staff accounts are refused (see api.auth.social). `apple_login_allow_staff` in
site_config turns that off, deliberately.
"""

import frappe
import jwt
import requests
from frappe import _
from frappe.utils import cint

from excel_restaurant_pos.api.auth.social import sign_in_verified_email
from excel_restaurant_pos.utils.error_handler import ErrorCode, throw_error

CLIENT_IDS_CONFIG_KEY = "apple_sign_in_client_ids"
ALLOW_STAFF_CONFIG_KEY = "apple_login_allow_staff"

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ALGORITHM = "RS256"

KEYS_CACHE_KEY = "apple_sign_in_keys"
KEYS_CACHE_SECONDS = 24 * 60 * 60
KEYS_FETCH_TIMEOUT_SECONDS = 10
# Apple rotates its keys, so a token signed with a key we have not cached makes
# us fetch them again -- but not more often than this, or forged tokens with
# made-up key IDs would turn every request into a call to Apple.
KEYS_REFRESH_LOCK_KEY = "apple_sign_in_keys_refreshed"
KEYS_REFRESH_MIN_SECONDS = 5 * 60

# Tolerate small clock differences between Apple and this server.
CLOCK_SKEW_SECONDS = 10

NAME_MAX_LENGTH = 140


def client_ids():
	"""The Services IDs and bundle IDs whose tokens this site accepts. Empty means off."""
	configured = frappe.conf.get(CLIENT_IDS_CONFIG_KEY)
	if not configured:
		return []
	if isinstance(configured, str):
		configured = [configured]

	return [str(value).strip() for value in configured if str(value).strip()]


def _refuse(message, detail, status=401):
	frappe.log_error(title="Apple sign-in refused", message=detail)
	throw_error(ErrorCode.UNAUTHORIZED, message, http_status_code=status)


def _fetch_apple_keys():
	response = requests.get(APPLE_KEYS_URL, timeout=KEYS_FETCH_TIMEOUT_SECONDS)
	response.raise_for_status()
	return response.json()["keys"]


def _apple_keys(refresh=False):
	cache = frappe.cache()
	keys = None if refresh else cache.get_value(KEYS_CACHE_KEY)
	if not keys:
		keys = _fetch_apple_keys()
		cache.set_value(KEYS_CACHE_KEY, keys, expires_in_sec=KEYS_CACHE_SECONDS)
	return keys


def _find_key(keys, kid):
	for jwk in keys:
		if jwk.get("kid") == kid:
			return jwt.PyJWK(jwk, algorithm=APPLE_ALGORITHM).key
	return None


def _signing_key(credential):
	kid = jwt.get_unverified_header(credential).get("kid")
	key = _find_key(_apple_keys(), kid)

	cache = frappe.cache()
	if key is None and not cache.get_value(KEYS_REFRESH_LOCK_KEY):
		cache.set_value(KEYS_REFRESH_LOCK_KEY, 1, expires_in_sec=KEYS_REFRESH_MIN_SECONDS)
		key = _find_key(_apple_keys(refresh=True), kid)

	if key is None:
		raise jwt.InvalidTokenError(f"no Apple key with kid {kid!r}")
	return key


def verify_credential(credential):
	"""Apple's claims for a genuine token addressed to us, or a refusal."""
	audiences = client_ids()
	if not audiences:
		throw_error(ErrorCode.UNAUTHORIZED, _("Apple sign-in is not enabled."), http_status_code=403)

	if not credential or not isinstance(credential, str):
		_refuse(_("Apple sign-in failed. Please try again."), "no credential supplied")

	try:
		claims = jwt.decode(
			credential,
			_signing_key(credential),
			algorithms=[APPLE_ALGORITHM],
			audience=audiences,
			issuer=APPLE_ISSUER,
			leeway=CLOCK_SKEW_SECONDS,
			options={"require": ["exp", "iat", "iss", "aud", "sub"]},
		)
	except Exception as exc:
		# Bad signature, wrong audience or issuer, expired, malformed -- or
		# Apple's keys could not be fetched. None of these may sign anyone in.
		_refuse(_("Apple sign-in failed. Please try again."), f"token rejected: {exc}")

	email = (claims.get("email") or "").strip().lower()
	if not email or str(claims.get("email_verified")).lower() != "true":
		_refuse(
			_("Your Apple ID's email address is not verified."),
			f"email={email!r} email_verified={claims.get('email_verified')!r}",
		)

	claims["email"] = email
	return claims


def _name_part(value):
	return value.strip()[:NAME_MAX_LENGTH] if isinstance(value, str) else ""


@frappe.whitelist(allow_guest=True, methods=["POST"])
def apple_login(credential=None, first_name=None, last_name=None):
	"""Sign in with an Apple identity token. Returns what api.auth.login returns."""
	frappe.set_user("Guest")

	claims = verify_credential(credential)
	return sign_in_verified_email(
		claims["email"],
		provider="Apple",
		allow_staff=cint(frappe.conf.get(ALLOW_STAFF_CONFIG_KEY)),
		first_name=_name_part(first_name),
		last_name=_name_part(last_name),
	)
