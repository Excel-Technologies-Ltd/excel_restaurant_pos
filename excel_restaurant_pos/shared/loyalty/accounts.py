"""Membership: enrolment, member tokens, lookup and account status."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, nowdate

from excel_restaurant_pos.shared.loyalty import ledger
from excel_restaurant_pos.shared.loyalty.settings import (
	ACCOUNT,
	TXN,
	get_active_programme,
	get_settings,
	is_enabled,
	is_excluded_customer,
	member_token_secret,
)

MEMBER_PREFIX = "LM-"
# No 0/O, 1/I: member numbers are read aloud and typed in at the counter.
MEMBER_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
MEMBER_LENGTH = 8
TOKEN_PREFIX = "AL1"
TOKEN_PATTERN = re.compile(r"^AL1\.(LM-[A-Z0-9]{8})\.(\d+)\.([0-9a-f]{16})$")

ACTIVE, SUSPENDED, CLOSED = "Active", "Suspended", "Closed"


# ---------------------------------------------------------------- identity


def generate_member_number() -> str:
	for _attempt in range(20):
		number = MEMBER_PREFIX + "".join(secrets.choice(MEMBER_ALPHABET) for _i in range(MEMBER_LENGTH))
		if not frappe.db.exists(ACCOUNT, number):
			return number
	frappe.throw(_("Could not allocate a member number. Please try again."))


def _signature(member_number: str, version: int, secret: str) -> str:
	message = f"{member_number}|{cint(version)}".encode()
	return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()[:16]


def build_token(member_number: str, version: int, secret: str | None = None) -> str:
	"""The barcode value on passes and in-app: it identifies, it never authorises."""
	secret = secret or member_token_secret()
	return f"{TOKEN_PREFIX}.{member_number}.{cint(version)}.{_signature(member_number, version, secret)}"


def parse_token(token: str, secret: str | None = None) -> tuple[str, int] | None:
	"""(member_number, version) when the signature is valid, else None."""
	match = TOKEN_PATTERN.match((token or "").strip())
	if not match:
		return None
	member_number, version, signature = match.group(1), cint(match.group(2)), match.group(3)
	expected = _signature(member_number, version, secret or member_token_secret())
	if not hmac.compare_digest(expected, signature):
		return None
	return member_number, version


def member_token(account) -> str:
	if isinstance(account, str):
		account = frappe.db.get_value(ACCOUNT, account, ["member_number", "token_version"], as_dict=True)
	return build_token(account.member_number, account.token_version)


def account_from_token(token: str) -> str | None:
	"""The account a scanned token belongs to; a reissued (older) token is refused."""
	parsed = parse_token(token)
	if not parsed:
		return None
	member_number, version = parsed
	current = frappe.db.get_value(ACCOUNT, member_number, "token_version")
	if current is None or cint(current) != version:
		return None
	return member_number


# ---------------------------------------------------------------- lookup


def account_for_customer(customer: str | None) -> str | None:
	if not customer:
		return None
	return frappe.db.get_value(ACCOUNT, {"customer": customer}, "name")


def user_for_customer(customer: str) -> str | None:
	user = frappe.db.get_value(
		"User Permission", {"allow": "Customer", "for_value": customer, "is_default": 1}, "user"
	) or frappe.db.get_value("User Permission", {"allow": "Customer", "for_value": customer}, "user")
	if user:
		return user
	email = frappe.db.get_value("Customer", customer, "email_id")
	return frappe.db.get_value("User", {"email": email}, "name") if email else None


def _customers_by_contact(field: str, value: str) -> list[str]:
	if field == "email":
		customers = frappe.get_all("Customer", filters={"email_id": value}, pluck="name")
		child, child_field = "Contact Email", "email_id"
	else:
		customers = frappe.get_all("Customer", filters={"mobile_no": value}, pluck="name")
		child, child_field = "Contact Phone", "phone"

	linked = frappe.db.sql(
		f"""
		SELECT DISTINCT dl.link_name
		FROM `tab{child}` c
		JOIN `tabDynamic Link` dl ON dl.parent = c.parent AND dl.parenttype = 'Contact'
		WHERE c.{child_field} = %s AND dl.link_doctype = 'Customer'
		""",
		value,
		pluck=True,
	)
	return list(dict.fromkeys([*customers, *linked]))


def find_accounts(query: str) -> list[str]:
	"""Accounts matching a scanned token, member number, phone or email."""
	query = (query or "").strip()
	if not query:
		return []

	if query.startswith(f"{TOKEN_PREFIX}."):
		account = account_from_token(query)
		return [account] if account else []

	if query.upper().startswith(MEMBER_PREFIX):
		number = query.upper()
		return [number] if frappe.db.exists(ACCOUNT, number) else []

	field = "email" if "@" in query else "phone"
	value = query.lower() if field == "email" else query
	customers = _customers_by_contact(field, value)
	if not customers:
		return []
	return frappe.get_all(ACCOUNT, filters={"customer": ["in", customers]}, pluck="name")


def mask_email(email: str | None) -> str | None:
	if not email or "@" not in email:
		return None
	local, domain = email.split("@", 1)
	suffix = domain[domain.rfind(".") :] if "." in domain else ""
	return f"{local[:1]}***@{domain[:1]}***{suffix}"


def mask_phone(phone: str | None) -> str | None:
	digits = re.sub(r"\D", "", phone or "")
	return f"***{digits[-4:]}" if len(digits) >= 4 else None


# ---------------------------------------------------------------- enrolment


def enrol(customer: str, source: str = "Admin", user: str | None = None, programme=None) -> str | None:
	"""Enrol a customer, or return their existing account. None when they cannot join."""
	if not is_enabled():
		return None
	programme = programme or get_active_programme()
	if not programme or is_excluded_customer(customer):
		return None
	if not frappe.db.exists("Customer", customer):
		return None

	existing = account_for_customer(customer)
	if existing:
		if user and not frappe.db.get_value(ACCOUNT, existing, "user"):
			frappe.db.set_value(ACCOUNT, existing, "user", user, update_modified=False)
		return existing

	from excel_restaurant_pos.shared.loyalty.tiers import lowest_tier

	settings = get_settings()
	tier = lowest_tier(programme)
	doc = frappe.get_doc(
		{
			"doctype": ACCOUNT,
			"customer": customer,
			"user": user or user_for_customer(customer),
			"programme": programme.name,
			"status": ACTIVE,
			"enrolled_on": now_datetime(),
			"enrolment_source": source,
			"tier": tier.tier_name if tier else None,
			"tier_since": nowdate() if tier else None,
			"notify_email": cint(settings.notify_email),
			"notify_push": cint(settings.notify_push),
		}
	)

	savepoint = "arcpos_loyalty_enrol"
	frappe.db.savepoint(savepoint)
	try:
		doc.insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# Enrolment raced with itself (sign-up and a first order at once).
		frappe.db.rollback(save_point=savepoint)
		return account_for_customer(customer)
	return doc.name


def on_web_signup(customer: str, user: str):
	"""Called whenever a storefront account is linked to its Customer.

	Never allowed to break sign-up or login: a failure is logged and rolled
	back to the savepoint, and the customer is enrolled later on a first order.
	"""
	savepoint = "arcpos_loyalty_signup"
	frappe.db.savepoint(savepoint)
	try:
		# The settings reads are inside the guard too: a cache or DB hiccup
		# reading them must not break sign-up either.
		if not is_enabled() or not cint(get_settings().auto_enrol_on_signup):
			return
		account = enrol(customer, source="Signup", user=user)
		if account:
			from excel_restaurant_pos.shared.loyalty.events import emit

			emit("customer_signup", customer, reference_doctype="Customer", reference_name=customer)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(title="Loyalty enrolment on sign-up failed", message=frappe.get_traceback())


# ---------------------------------------------------------------- status


def set_status(account: str, status: str, remarks: str | None = None):
	if status not in (ACTIVE, SUSPENDED, CLOSED):
		frappe.throw(_("Invalid account status {0}.").format(status))

	ledger.lock_account(account)
	current = frappe.db.get_value(ACCOUNT, account, "status")
	if current == CLOSED and status != CLOSED:
		frappe.throw(_("A closed loyalty account cannot be reopened."))
	if current == status:
		return

	frappe.db.set_value(ACCOUNT, account, "status", status)
	frappe.get_doc(ACCOUNT, account).add_comment(
		"Info", _("Status changed from {0} to {1}. {2}").format(current, status, remarks or "")
	)

	if status == CLOSED:
		lots = frappe.get_all(
			TXN,
			filters={
				"account": account,
				"points": [">", 0],
				"status": ["in", ["Pending", "Available"]],
				"remaining_points": [">", 0],
			},
			pluck="name",
		)
		for lot in lots:
			ledger.expire_lot(account, lot, f"expire:{lot}:closed", remarks=_("Account closed"))

	ledger.recompute_cache(account)

	if status == CLOSED:
		from excel_restaurant_pos.shared.loyalty.wallet.sync import void_passes

		void_passes(account)


def reissue_token(account: str) -> str:
	"""Invalidate the current barcode (lost phone, shared screenshot) and push new passes."""
	ledger.lock_account(account)
	version = cint(frappe.db.get_value(ACCOUNT, account, "token_version")) + 1
	frappe.db.set_value(ACCOUNT, account, "token_version", version)
	frappe.get_doc(ACCOUNT, account).add_comment("Info", _("Member barcode reissued (version {0}).").format(version))

	from excel_restaurant_pos.shared.loyalty.wallet.sync import schedule_sync

	schedule_sync(account, force=True)
	return member_token(account)


def assert_active(account: str):
	status = frappe.db.get_value(ACCOUNT, account, "status")
	if status != ACTIVE:
		frappe.throw(_("Loyalty account {0} is {1}.").format(account, (status or "").lower()))
