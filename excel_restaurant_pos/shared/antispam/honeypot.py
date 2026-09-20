"""Honeypot checks for the public order endpoint.

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
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

# Fields the checkout renders out of sight. A real customer never fills one, so
# any value at all means the request was machine generated. They are named after
# plausible form fields on purpose -- a field called `honeypot` teaches a bot to
# skip it.
HONEYPOT_FIELDS = ("website", "fax_number", "company_website")

# A human cannot read a menu, pick items and fill an address this fast. The
# client stamps `checkout_started_at` when the checkout screen opens.
MIN_CHECKOUT_SECONDS = 3

# Anything older than this is a stale tab rather than a real checkout, and is
# left alone -- rejecting it would punish someone who wandered off mid order.
MAX_CHECKOUT_SECONDS = 6 * 60 * 60


def _client_ip():
	return getattr(frappe.local, "request_ip", None) or "unknown"


def _reject(reason, detail):
	"""Log loudly, refuse blandly.

	The caller is told nothing about which guard fired. A message naming the
	honeypot field is a free tutorial on how to get past it.
	"""
	frappe.log_error(
		title=f"Order rejected: {reason}",
		message=f"ip={_client_ip()} {detail}",
	)
	frappe.throw(
		_("This order could not be placed. Please try again."), frappe.ValidationError
	)


def _check_hidden_fields(data):
	for fieldname in HONEYPOT_FIELDS:
		value = data.get(fieldname)
		if value is not None and str(value).strip():
			_reject("honeypot", f"field={fieldname!r} value={str(value)[:80]!r}")


def _check_elapsed_time(data):
	"""Reject an order submitted faster than a person could fill the form.

	Optional and backward compatible: a client that does not send
	`checkout_started_at` is not checked. The timestamp is client supplied, so
	this is a speed bump for scripted orders, not a gate -- a determined caller
	just sends an older one. Making it a real gate means signing it server side;
	see docs/order-antispam.md.
	"""
	raw = data.get("checkout_started_at")
	if not raw:
		return

	try:
		started = get_datetime(raw)
	except Exception:
		# A malformed timestamp is a client bug, not an attack. Ignore it rather
		# than refuse an order that may be perfectly real.
		return

	elapsed = (now_datetime() - started).total_seconds()
	if elapsed < 0 or elapsed > MAX_CHECKOUT_SECONDS:
		# Clock skew, or a tab left open since this morning.
		return

	if elapsed < MIN_CHECKOUT_SECONDS:
		_reject("too fast", f"elapsed={elapsed:.2f}s min={MIN_CHECKOUT_SECONDS}s")


def check_order_honeypot(data=None):
	"""Run the cheap bot checks over an incoming order.

	Disabled by setting `arcpos_disable_order_honeypot` in site_config.json,
	which exists so a broken client cannot take ordering down at 7pm on a
	Friday.
	"""
	if cint(frappe.conf.get("arcpos_disable_order_honeypot")):
		return

	data = frappe.form_dict if data is None else data
	_check_hidden_fields(data)
	_check_elapsed_time(data)
