"""Member notifications: email and Expo push, each sent at most once per key."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money, now_datetime, strip_html

from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, NOTIFICATION_LOG, get_programme, get_settings, is_enabled

# kind -> (subject, html body). Overridden by the Email Template set in settings.
DEFAULTS = {
	"earned": (
		"You earned {{ points }} points",
		"<p>Hi {{ first_name }},</p><p>You earned <b>{{ points }}</b> points{% if invoice %} on order {{ invoice }}{% endif %}."
		"{% if pending %} They become available after the return window.{% endif %}</p>"
		"<p>Balance: <b>{{ balance }}</b> points ({{ balance_value }}).</p>",
	),
	"available": (
		"Your points are ready to use",
		"<p>Hi {{ first_name }},</p><p>Your points are now available. Balance: <b>{{ balance }}</b> points ({{ balance_value }}).</p>",
	),
	"redeemed": (
		"You used {{ points }} points",
		"<p>Hi {{ first_name }},</p><p>You used <b>{{ points }}</b> points ({{ value_formatted }}) on order {{ invoice }}.</p>"
		"<p>Balance: <b>{{ balance }}</b> points.</p>",
	),
	"expiring": (
		"{{ points }} points expire on {{ expiry_date }}",
		"<p>Hi {{ first_name }},</p><p><b>{{ points }}</b> of your points expire on {{ expiry_date }}. Use them before then!</p>",
	),
	"tier_change": (
		"You are now {{ to_tier }}",
		"<p>Hi {{ first_name }},</p><p>Your membership tier is now <b>{{ to_tier }}</b>.</p>",
	),
	"voucher": (
		"Your reward: {{ reward_name }}",
		"<p>Hi {{ first_name }},</p><p>Your voucher code is <b>{{ coupon_code }}</b>, valid until {{ valid_upto }}.</p>",
	),
	"otp": (
		"Your verification code",
		"<p>Your code to use <b>{{ points }}</b> loyalty points is <b style='letter-spacing:3px'>{{ code }}</b>. "
		"It expires in 5 minutes. Only share it if you asked to use {{ points }} points.</p>",
	),
}

TEMPLATE_FIELDS = {
	"earned": "email_template_earned",
	"redeemed": "email_template_redeemed",
	"expiring": "email_template_expiring",
	"tier_change": "email_template_tier",
	"voucher": "email_template_voucher",
	"otp": "email_template_otp",
}
PUSH_ONLY = {"available"}
EMAIL_ONLY = {"voucher", "otp"}


def enqueue_notification(account: str, kind: str, key: str, context: dict | None = None):
	"""Send after the current transaction commits, so a rolled-back award notifies nobody."""
	if not account or not is_enabled():
		return
	frappe.enqueue(
		"excel_restaurant_pos.shared.loyalty.notifications.send_notification",
		queue="short",
		enqueue_after_commit=True,
		account=account,
		kind=kind,
		key=key,
		context=context or {},
	)


def _claim(account: str, kind: str, key: str) -> str | None:
	"""Reserve the notification key; None when it was already sent."""
	savepoint = "arcpos_loyalty_notify"
	frappe.db.savepoint(savepoint)
	try:
		log = frappe.get_doc(
			{"doctype": NOTIFICATION_LOG, "account": account, "kind": kind, "key": key[:140], "sent_at": now_datetime()}
		).insert(ignore_permissions=True)
		return log.name
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		frappe.db.rollback(save_point=savepoint)
		return None


def _member(account_name: str) -> frappe._dict:
	account = frappe.db.get_value(
		ACCOUNT,
		account_name,
		["name", "customer", "customer_name", "user", "programme", "available_points", "notify_email", "notify_push", "tier"],
		as_dict=True,
	)
	email = frappe.db.get_value("Customer", account.customer, "email_id")
	if not email and account.user:
		email = frappe.db.get_value("User", account.user, "email")
	account.email = email
	return account


def _context(account, context: dict) -> dict:
	programme = get_programme(account.programme)
	settings = get_settings()
	currency = frappe.db.get_value("Company", programme.company, "default_currency") if programme else None
	balance = cint(account.available_points)
	value = balance * flt(programme.point_value if programme else 0)
	return {
		**context,
		"first_name": (account.customer_name or "").split(" ")[0] or _("there"),
		"member_number": account.name,
		"tier": account.tier,
		"balance": balance,
		"balance_value": fmt_money(value, currency=currency),
		"value_formatted": fmt_money(flt(context.get("value")), currency=currency),
		"programme_name": (settings.programme_display_name if settings else None)
		or (programme.programme_name if programme else ""),
	}


def render(kind: str, context: dict) -> tuple[str, str]:
	settings = get_settings()
	template = settings.get(TEMPLATE_FIELDS.get(kind, "")) if settings else None
	if template and frappe.db.exists("Email Template", template):
		tpl = frappe.get_cached_doc("Email Template", template)
		body = tpl.response_html if cint(tpl.use_html) else tpl.response
		return frappe.render_template(tpl.subject, context), frappe.render_template(body or "", context)
	subject, body = DEFAULTS[kind]
	return frappe.render_template(subject, context), frappe.render_template(body, context)


def expo_tokens(user: str | None) -> list[str]:
	if not user or not frappe.db.table_exists("Push Token List"):
		return []
	return frappe.db.sql(
		"""
		SELECT ptl.token
		FROM `tabPush Token List` ptl
		JOIN `tabArcPOS Notification Token` nt ON nt.name = ptl.parent
		WHERE nt.user = %s AND IFNULL(ptl.token, '') != ''
		""",
		user,
		pluck=True,
	)


def push(user: str | None, title: str, body: str, data: dict | None = None) -> bool:
	tokens = expo_tokens(user)
	if not tokens:
		return False
	try:
		from exponent_server_sdk import PushClient, PushMessage
	except ImportError:
		return False

	messages = [
		PushMessage(to=token, title=title, body=body, data=data or {})
		for token in tokens
		if PushClient.is_exponent_push_token(token)
	]
	if not messages:
		return False
	PushClient().publish_multiple(messages)
	return True


def send_notification(account: str, kind: str, key: str, context: dict | None = None):
	if kind not in DEFAULTS or not frappe.db.exists(ACCOUNT, account):
		return
	log = _claim(account, kind, key)
	if not log:
		return

	member = _member(account)
	ctx = _context(member, context or {})
	subject, body = render(kind, ctx)
	channels, errors = [], []

	if kind not in PUSH_ONLY and cint(member.notify_email) and member.email:
		try:
			frappe.sendmail(
				recipients=[member.email], subject=subject, message=body, reference_doctype=ACCOUNT, reference_name=account
			)
			channels.append("email")
		except Exception as exc:
			errors.append(f"email: {exc}")

	if kind not in EMAIL_ONLY and cint(member.notify_push) and member.user:
		try:
			if push(member.user, subject, strip_html(body).strip(), {"type": f"loyalty_{kind}", "account": account}):
				channels.append("push")
		except Exception as exc:
			errors.append(f"push: {exc}")

	if kind == "expiring":
		try:
			from excel_restaurant_pos.shared.loyalty.wallet.sync import send_pass_message

			if send_pass_message(account, subject, strip_html(body).strip()):
				channels.append("wallet")
		except Exception as exc:
			errors.append(f"wallet: {exc}")

	frappe.db.set_value(
		NOTIFICATION_LOG, log, {"channels": ", ".join(channels), "error": "\n".join(errors) or None}, update_modified=False
	)
	frappe.db.commit()


def send_code(account: str, code: str, points: int | None = None) -> str | None:
	"""Email a step-up code right away (never queued: the cashier is waiting)."""
	from excel_restaurant_pos.shared.loyalty.accounts import mask_email

	member = _member(account)
	if not member.email:
		frappe.throw(_("The member has no email address to send a code to."))
	subject, body = render("otp", _context(member, {"code": code, "points": points}))
	frappe.sendmail(recipients=[member.email], subject=subject, message=body, now=True)
	if member.user:
		try:
			push(member.user, subject, strip_html(body).strip(), {"type": "loyalty_otp"})
		except Exception:
			frappe.log_error(title="Loyalty OTP push failed", message=frappe.get_traceback())
	return mask_email(member.email)
