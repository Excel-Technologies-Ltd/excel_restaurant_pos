"""Roles and Customer records for accounts created from the storefront.

Both ways of signing up -- email with an OTP (overrides/user.verify_otp) and
Google (api/auth/google) -- go through here, so a web account is the same
account however it was made. Deciding roles in two places is how they drift.
"""

import frappe

# order-web reads a customer's own invoices through the generic document API
# (My Orders -> useGetFrappeDocListQuery on Sales Invoice), and today that read
# comes from Sales User. Sales User also grants create/submit on Sales Invoice on
# this site, which is a known hole; narrowing it belongs here, once, for both
# sign-up paths.
EXTRA_WEB_ROLES = ("Sales User",)

# Values for Customer fields other apps make mandatory, as a dict in
# site_config -- e.g. {"custom_zone": "Web"}. excel_erpnext requires
# Customer.custom_zone (a Zone link) with no default, and nothing here could
# know which zone a web customer belongs to, so without this no web Customer
# can be created at all.
DEFAULTS_CONFIG_KEY = "arcpos_web_customer_defaults"


def web_customer_roles():
	"""Roles a storefront account is given."""
	default_role = (
		frappe.db.get_single_value("ArcPOS System Settings", "user_default_role") or "Customer"
	)
	return [default_role, *EXTRA_WEB_ROLES]


def _web_customer_defaults():
	value = frappe.conf.get(DEFAULTS_CONFIG_KEY) or {}
	return value if isinstance(value, dict) else {}


def _create_customer(user_doc, mobile_no):
	selling_settings = frappe.get_single("Selling Settings")
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": user_doc.full_name or user_doc.email,
			"email_id": user_doc.email,
			"mobile_no": mobile_no,
			"customer_type": "Individual",
			"customer_group": selling_settings.customer_group or "All Customer Groups",
			"territory": selling_settings.territory or "All Territories",
		}
	)

	meta = frappe.get_meta("Customer")
	for fieldname, value in _web_customer_defaults().items():
		if meta.has_field(fieldname) and not customer.get(fieldname):
			customer.set(fieldname, value)

	# Say which setting fixes it, rather than a bare MandatoryError.
	missing = [
		df.fieldname
		for df in meta.fields
		if df.reqd and df.fieldname.startswith(("custom_", "excel_")) and not customer.get(df.fieldname)
	]
	if missing:
		frappe.throw(
			frappe._(
				"A web customer cannot be created: {0} is required. Set a default for it in "
				"site_config under {1}, e.g. {{\"{2}\": \"...\"}}."
			).format(", ".join(missing), DEFAULTS_CONFIG_KEY, missing[0]),
			frappe.ValidationError,
		)

	return customer.insert(ignore_permissions=True).name


def _ensure_user_permission(user, allow, for_value):
	if frappe.db.exists("User Permission", {"user": user, "allow": allow, "for_value": for_value}):
		return

	frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": user,
			"allow": allow,
			"for_value": for_value,
			"is_default": 1,
			"apply_to_all_doctypes": 1,
		}
	).insert(ignore_permissions=True)


def ensure_customer_for_user(user_doc, mobile_no=None):
	"""The Customer behind a web account, created if needed, and the account
	restricted to it.

	The permissions are ensured every time, not only when the Customer is new.
	Sign-up used to create them only alongside a new Customer, so an account
	whose email already had a Customer -- one made at the POS, say -- got Sales
	User with no restriction at all, and with it read access to every invoice.
	"""
	customer = frappe.db.get_value("Customer", {"email_id": user_doc.email}, "name")

	if not customer:
		customer = _create_customer(user_doc, mobile_no)

	_ensure_user_permission(user_doc.name, "Customer", customer)
	_ensure_user_permission(user_doc.name, "User", user_doc.email)
	return customer
