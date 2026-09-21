"""Cloudflare Turnstile verification for the public forms: checkout, sign-up, login.

Unlike the honeypot next door, this one survives contact with a real attacker:
a Turnstile token is single use and short lived, so copying the checkout request
out of the network tab and replaying it presents a token Cloudflare has already
spent. That is the difference between a speed bump and a control.

It is still only a proof that a browser solved a challenge. Someone willing to
sit and place a fake order by hand through the real checkout passes it every
time. Payment and a verified phone number are what stop that; this stops the
automation.

Three decisions worth keeping in mind before changing anything here:

- It runs *after* the idempotency replay check, never before. Tokens are single
  use, so a client retrying a dropped checkout re-sends a token that is already
  spent -- verifying first would fail every genuine retry.
- It fails open when Cloudflare cannot be reached, or when our own keys are
  wrong, and fails closed only on a token Cloudflare actively rejected. A
  restaurant should not stop taking orders because somebody else is having an
  outage.
- Everyone but staff. A POS terminal must not be challenged; that is decided
  by the account's roles (shared/customer_access.is_staff), which the server
  knows, not `custom_order_from`, which the caller can set to anything.

The widget lives on the storefront domain and this runs on the API domain, which
is the normal arrangement: the sitekey is bound to wherever the widget renders,
and siteverify is a server to server call that never looks at who is calling it.
What that does mean is that the only evidence of *which* domain minted a token
is the `hostname` Cloudflare returns, so pin it -- see `arcpos_turnstile_hostnames`.
"""

import frappe
import requests
from frappe.utils import cint

from excel_restaurant_pos.shared.antispam.forms import CHECKOUT, log_title, refusal_message
from excel_restaurant_pos.shared.customer_access import is_staff

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# site_config.json keys. The secret never belongs in code or in a fixture.
SECRET_CONFIG_KEY = "arcpos_turnstile_secret"
ACTION_CONFIG_KEY = "arcpos_turnstile_action"
HOSTNAME_CONFIG_KEY = "arcpos_turnstile_hostnames"
DISABLE_CONFIG_KEY = "arcpos_disable_turnstile"

# The widget posts `cf-turnstile-response`; the others are for clients that
# cannot send a hyphenated form key.
TOKEN_FIELDS = ("cf-turnstile-response", "cf_turnstile_response", "turnstile_token")

# Checkout is on the critical path. Cloudflare answers in well under a second
# normally, so anything past this is an outage, and we would rather take the
# order than make the customer wait.
VERIFY_TIMEOUT = 5

# Cloudflare blaming our configuration rather than the caller's token. Refusing
# the order would punish the customer for our mistake.
OUR_FAULT_CODES = {"missing-input-secret", "invalid-input-secret", "bad-request"}


def _client_ip():
	return getattr(frappe.local, "request_ip", None) or None


def _reject(detail, form=CHECKOUT):
	"""Log the real reason, tell the caller nothing.

	The message is deliberately the same one the honeypot uses: which guard
	fired is not the caller's business.
	"""
	frappe.log_error(
		title=log_title(form, "turnstile"),
		message=f"ip={_client_ip() or 'unknown'} {detail}",
	)
	frappe.throw(refusal_message(form), frappe.ValidationError)


def configured():
	"""Whether Turnstile is switched on for this site.

	Presence of the secret is the switch, so the backend can ship before the
	storefront starts sending tokens without refusing every order in between.
	"""
	if cint(frappe.conf.get(DISABLE_CONFIG_KEY)):
		return False

	return bool(frappe.conf.get(SECRET_CONFIG_KEY))


def has_token(data=None):
	data = frappe.form_dict if data is None else data
	return bool(_read_token(data))


def _read_token(data):
	for fieldname in TOKEN_FIELDS:
		value = data.get(fieldname)
		if value and str(value).strip():
			return str(value).strip()

	return None


def _siteverify(secret, token):
	"""Ask Cloudflare about the token.

	Returns Cloudflare's answer, or None when we could not get one -- a timeout,
	a network error, a 5xx, a body that is not JSON. None means "no opinion",
	and the caller lets the order through.
	"""
	try:
		response = requests.post(
			VERIFY_URL,
			data={"secret": secret, "response": token, "remoteip": _client_ip()},
			timeout=VERIFY_TIMEOUT,
		)
		if response.status_code >= 500:
			frappe.log_error(
				title="Turnstile unavailable",
				message=f"siteverify returned {response.status_code}; request allowed through",
			)
			return None

		return response.json()
	except Exception:
		frappe.log_error(
			title="Turnstile unavailable",
			message=f"{frappe.get_traceback()}\nrequest allowed through",
		)
		return None


def _allowed_hostnames():
	"""Hostnames whose widget may mint a token for this endpoint.

	A string or a list in site_config; empty means no check.
	"""
	configured_hosts = frappe.conf.get(HOSTNAME_CONFIG_KEY)
	if not configured_hosts:
		return []
	if isinstance(configured_hosts, str):
		configured_hosts = [configured_hosts]

	return [str(host).strip().lower() for host in configured_hosts if str(host).strip()]


def _expected_action(form):
	"""The `action` the widget for `form` sets, or None when actions are not pinned.

	`arcpos_turnstile_action` switches the check on. A dict names each form's
	action; any other value pins every form to its own name (checkout, signup,
	login). A plain string is the checkout widget's action -- what the setting
	meant before sign-up and login had widgets -- and pins the others too.
	"""
	configured_action = frappe.conf.get(ACTION_CONFIG_KEY)
	if not configured_action:
		return None
	if isinstance(configured_action, dict):
		return configured_action.get(form)
	if form == CHECKOUT and isinstance(configured_action, str) and configured_action not in ("1", "true"):
		return configured_action

	return form


def _check_origin(outcome, form=CHECKOUT):
	"""Pin the token to the widget it was supposed to come from.

	`action` says which widget on the page, `hostname` says which site. With the
	storefront on its own domain these are the only evidence of origin the
	verification carries, and both are reported by Cloudflare rather than by the
	caller, so neither can be forged by whoever posts the order.

	Both checks are off unless configured, so a site that has not set them keeps
	taking orders.
	"""
	expected_action = _expected_action(form)
	action = outcome.get("action")
	if expected_action and action != expected_action:
		# A token minted by another widget on the site -- the login form's, say
		# -- replayed here.
		_reject(f"action={action!r} expected={expected_action!r}", form)

	allowed = _allowed_hostnames()
	hostname = (outcome.get("hostname") or "").lower()
	if allowed and hostname not in allowed:
		# A token minted on some other site that shares this widget.
		_reject(f"hostname={hostname!r} allowed={allowed!r}", form)


def verify_order_turnstile(data=None):
	verify_turnstile(data, CHECKOUT)


def verify_turnstile(data=None, form=CHECKOUT):
	"""Verify the Turnstile token on a submitted public form.

	Does nothing when Turnstile is not configured, or when the caller is staff.
	Raises ValidationError when a token is missing or Cloudflare rejects it.
	"""
	if not configured():
		return

	# Staff are not challenged: a POS terminal must not hit a captcha. Everyone
	# else is, signed in or not. This used to skip every signed-in caller, which
	# was only staff while guests could order -- now that ordering needs an
	# account, it would have skipped every order.
	if is_staff():
		return

	data = frappe.form_dict if data is None else data

	token = _read_token(data)
	if not token:
		_reject("no token supplied", form)

	outcome = _siteverify(frappe.conf.get(SECRET_CONFIG_KEY), token)
	if outcome is None:
		# Cloudflare had no answer for us. Let it through.
		return

	if outcome.get("success"):
		_check_origin(outcome, form)
		return

	codes = outcome.get("error-codes") or []
	if set(codes) & OUR_FAULT_CODES:
		# Our keys are wrong. That is an operations problem, not a spam order.
		frappe.log_error(
			title="Turnstile misconfigured",
			message=f"siteverify rejected our own credentials: {codes}; request allowed through",
		)
		return

	# timeout-or-duplicate is the interesting one: a replayed or expired token.
	_reject(f"rejected by cloudflare: {codes}", form)
