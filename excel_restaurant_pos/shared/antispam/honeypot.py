"""Honeypot checks for the public forms: checkout, sign-up and login.

What this does and does not do, so nobody mistakes it for an access control:

It catches a bot that fills in every field it can find. The checkout form
renders a field no human ever sees, so anything arriving with a value in it was
filled by a machine reading the markup.

It does NOT catch somebody who opened the network tab, copied the request the
real checkout makes and replayed it -- their copy simply does not carry the
field. That is the attack an anonymous order endpoint actually attracts, and
what stops it is payment or a verified phone number, not this.

So: cheap, no UX cost, worth having, and the weakest of the guards on this
route. Keep it in that order of importance.
"""

import frappe
from zoneinfo import ZoneInfo

from frappe.utils import cint, get_datetime, get_system_timezone, now_datetime

from excel_restaurant_pos.shared.antispam.forms import CHECKOUT, LOGIN, SIGNUP, log_title, refusal_message

# Fields the checkout renders out of sight. A real customer never fills one, so
# any value at all means the request was machine generated. They are named after
# plausible form fields on purpose -- a field called `honeypot` teaches a bot to
# skip it.
HONEYPOT_FIELDS = ("website", "fax_number", "company_website")

# A human cannot read a menu, pick items and fill an address this fast. The
# client stamps `checkout_started_at` when the checkout screen opens.
MIN_CHECKOUT_SECONDS = 3

# Fastest believable submission per form, in seconds; None skips the timing
# check. Sign-up is a real form to type into. Login is not timed: a password
# manager fills it and a person submits it well inside a second.
MIN_SECONDS = {CHECKOUT: MIN_CHECKOUT_SECONDS, SIGNUP: MIN_CHECKOUT_SECONDS, LOGIN: None}

# When the form was opened. Checkout keeps its original name.
STARTED_AT_FIELDS = ("form_started_at", "checkout_started_at")

# Anything older than this is a stale tab rather than a real checkout, and is
# left alone -- rejecting it would punish someone who wandered off mid order.
MAX_CHECKOUT_SECONDS = 6 * 60 * 60


def _client_ip():
	return getattr(frappe.local, "request_ip", None) or "unknown"


def _reject(reason, detail, form=CHECKOUT):
	"""Log loudly, refuse blandly.

	The caller is told nothing about which guard fired. A message naming the
	honeypot field is a free tutorial on how to get past it.
	"""
	frappe.log_error(
		title=log_title(form, reason),
		message=f"ip={_client_ip()} {detail}",
	)
	frappe.throw(refusal_message(form), frappe.ValidationError)


def _check_hidden_fields(data, form):
	for fieldname in HONEYPOT_FIELDS:
		value = data.get(fieldname)
		if value is not None and str(value).strip():
			_reject("honeypot", f"field={fieldname!r} value={str(value)[:80]!r}", form)


def _as_server_time(started):
	"""A timestamp in the server's own wall-clock time, without tzinfo.

	The storefront sends UTC (an ISO string ending in Z), because the customer's
	device and the server need not share a timezone -- and here they do not:
	customers are in Canada while the site runs on Asia/Dhaka. Comparing the
	browser's local time with the server's clock put every real order about ten
	hours "old", past MAX_CHECKOUT_SECONDS, so the check was silently skipped
	for everyone. A naive value is still taken as server time, for any client
	that sends one.
	"""
	if started.tzinfo is None:
		return started

	return started.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def _check_elapsed_time(data, form):
	"""Reject a form submitted faster than a person could fill it.

	Optional and backward compatible: a client that does not send
	`form_started_at` (or `checkout_started_at`) is not checked. The timestamp is client supplied, so
	this is a speed bump for scripted orders, not a gate -- a determined caller
	just sends an older one. Making it a real gate means signing it server side;
	see docs/order-antispam.md.
	"""
	minimum = MIN_SECONDS[form]
	raw = next((data.get(f) for f in STARTED_AT_FIELDS if data.get(f)), None)
	if minimum is None or not raw:
		return

	try:
		started = _as_server_time(get_datetime(raw))
		elapsed = (now_datetime() - started).total_seconds()
	except Exception:
		# A malformed timestamp is a client bug, not an attack. Ignore it rather
		# than refuse an order that may be perfectly real.
		return

	if elapsed < 0 or elapsed > MAX_CHECKOUT_SECONDS:
		# Clock skew, or a tab left open since this morning.
		return

	if elapsed < minimum:
		_reject("too fast", f"elapsed={elapsed:.2f}s min={minimum}s", form)


def check_honeypot(data=None, form=CHECKOUT):
	"""Run the cheap bot checks over a submitted public form.

	Disabled everywhere by setting `arcpos_disable_order_honeypot` in
	site_config.json, which exists so a broken client cannot take ordering (or
	signing in) down at 7pm on a Friday. The name predates the other forms.
	"""
	if cint(frappe.conf.get("arcpos_disable_order_honeypot")):
		return

	data = frappe.form_dict if data is None else data
	_check_hidden_fields(data, form)
	_check_elapsed_time(data, form)


def check_order_honeypot(data=None):
	check_honeypot(data, CHECKOUT)
