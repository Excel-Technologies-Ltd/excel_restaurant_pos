"""One order per idempotency key, enforced by the database.

A checkout that times out on a phone, a double tapped Place Order button, a
retry from a flaky connection -- each of these sends the same order twice, and
today each one makes a second invoice and a second meal.

The client generates one key per checkout attempt and reuses it on every retry
of that attempt. The first request creates the order and stamps the key on it;
any later request carrying the same key gets the *same* order back instead of a
new one.

The guarantee comes from a unique index on `custom_idempotency_key`, not from a
lookup: two simultaneous retries both see no existing order, both try to insert,
and the database refuses the second. That is the case a check-then-insert would
get wrong, and it is exactly the case a flaky connection produces.

This is a correctness guard, not an abuse control. The key is chosen by the
caller, so anyone wanting two orders simply sends two keys -- which is the
correct behaviour for two genuine orders.
"""

import re

import frappe
from frappe import _

IDEMPOTENCY_FIELD = "custom_idempotency_key"
IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENCY_BODY_KEYS = ("idempotency_key", "idempotencyKey")

# Wide enough for a UUID, a ULID or a prefixed key; tight enough that the value
# is safe to log and cannot be used to smuggle anything into the column.
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

INVOICE_DOCTYPE = "Sales Invoice"


def _header_key():
	# frappe.request is an unbound proxy outside a web request (a background
	# job, a bench command), where reading it raises rather than returning None.
	if not getattr(frappe.local, "request", None):
		return None

	return frappe.get_request_header(IDEMPOTENCY_HEADER)


def read_key(data=None):
	"""The idempotency key for this request, or None.

	Header first, since that is where the convention puts it, falling back to
	the body for clients that cannot set headers on a form post.
	"""
	key = _header_key()

	if not key:
		data = frappe.form_dict if data is None else data
		for body_key in IDEMPOTENCY_BODY_KEYS:
			value = data.get(body_key)
			if value:
				key = value
				break

	if not key:
		return None

	key = str(key).strip()
	if not KEY_PATTERN.match(key):
		frappe.throw(
			_("{0} must be 8 to 128 characters of letters, digits, dot, dash, colon or underscore.").format(
				IDEMPOTENCY_HEADER
			),
			frappe.ValidationError,
		)

	return key


def supported():
	"""Whether the key column exists on this site.

	The field ships as a fixture, so a site that has not migrated yet should
	keep taking orders rather than fail every one of them.
	"""
	return frappe.get_meta(INVOICE_DOCTYPE).has_field(IDEMPOTENCY_FIELD)


def find_invoice(key):
	"""The invoice already created under this key, if there is one."""
	if not key or not supported():
		return None

	name = frappe.db.get_value(INVOICE_DOCTYPE, {IDEMPOTENCY_FIELD: key}, "name")
	if not name:
		return None

	return frappe.get_doc(INVOICE_DOCTYPE, name)


def stamp(sales_invoice, key):
	if key and supported():
		sales_invoice.set(IDEMPOTENCY_FIELD, key)


def save_once(sales_invoice, key):
	"""Save the invoice, returning the existing one if this key already made it.

	Wrapped in a savepoint: a duplicate key raises inside the database, which
	leaves the transaction unusable for the lookup that follows unless we roll
	back to a point before the failed insert.
	"""
	if not key or not supported():
		sales_invoice.save(ignore_permissions=True)
		return sales_invoice, False

	savepoint = "arcpos_idempotent_insert"
	frappe.db.savepoint(savepoint)
	try:
		sales_invoice.save(ignore_permissions=True)
		return sales_invoice, False
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# A concurrent retry of the same checkout won the race.
		frappe.db.rollback(save_point=savepoint)
		existing = find_invoice(key)
		if existing:
			return existing, True
		# The unique violation was on something else entirely.
		raise
