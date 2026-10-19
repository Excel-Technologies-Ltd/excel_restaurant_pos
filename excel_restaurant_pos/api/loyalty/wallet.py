"""Add-to-wallet endpoints for members, and the Google Wallet callback."""

import hmac
import time
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import get_url

from excel_restaurant_pos.api.loyalty.common import own_account, require_enabled
from excel_restaurant_pos.shared.loyalty.settings import WALLET_PASS, get_settings
from excel_restaurant_pos.shared.loyalty.wallet import apple, google
from excel_restaurant_pos.shared.loyalty.wallet.base import render
from excel_restaurant_pos.utils import rate_limit_by_caller
from excel_restaurant_pos.utils.error_handler import success_response


def _active_account() -> str:
	require_enabled()
	_customer, account = own_account()
	if frappe.db.get_value("ArcPOS Loyalty Account", account, "status") != "Active":
		frappe.throw(_("Your loyalty account is not active."))
	return account


@frappe.whitelist(methods=["GET"])
def google_save_url():
	if not google.enabled():
		frappe.throw(_("Google Wallet is not available."))
	# Each call writes the object through Google's API.
	rate_limit_by_caller("loyalty_google_save_url", limit=10, seconds=60)
	account = _active_account()
	view = render(account)
	object_id = google.object_id(view.member_number)
	if not frappe.db.exists(WALLET_PASS, {"object_id": object_id}):
		frappe.get_doc(
			{"doctype": WALLET_PASS, "account": account, "platform": "Google", "object_id": object_id, "status": "Issued"}
		).insert(ignore_permissions=True)
	# save_url creates the class and the object before signing the link.
	url = google.save_url(view)
	frappe.db.commit()
	return success_response(_("Save to Google Wallet"), data={"url": url})


def _send_pkpass(account: str):
	pass_doc = apple.ensure_pass(account)
	data = apple.build_pkpass(render(account), pass_doc)
	frappe.db.commit()
	frappe.local.response.filename = f"{pass_doc.object_id}.pkpass"
	frappe.local.response.filecontent = data
	frappe.local.response.content_type = "application/vnd.apple.pkpass"
	frappe.local.response.type = "download"


@frappe.whitelist(methods=["GET"])
def apple_pass():
	"""The member's signed .pkpass (application/vnd.apple.pkpass), for native
	apps that can send the Authorization header. Browsers use apple_pass_link."""
	if not apple.enabled():
		frappe.throw(_("Apple Wallet is not available."))
	rate_limit_by_caller("loyalty_apple_pass", limit=10, seconds=60)
	_send_pkpass(_active_account())


LINK_TTL_SECONDS = 300


def _link_signature(account: str, expires: int) -> str:
	from excel_restaurant_pos.shared.loyalty.settings import member_token_secret

	message = f"apple-pass|{account}|{expires}".encode()
	return hmac.new(member_token_secret().encode(), message, "sha256").hexdigest()


@frappe.whitelist(methods=["GET"])
def apple_pass_link():
	"""A five-minute download link for the member's pass.

	iOS Safari only offers "Add to Apple Wallet" when it navigates to the
	.pkpass itself, and a navigation cannot carry the storefront's Bearer
	token -- so the link carries a short-lived signature instead.
	"""
	if not apple.enabled():
		frappe.throw(_("Apple Wallet is not available."))
	rate_limit_by_caller("loyalty_apple_pass_link", limit=10, seconds=60)
	account = _active_account()
	expires = int(time.time()) + LINK_TTL_SECONDS
	token = f"{account}.{expires}.{_link_signature(account, expires)}"
	url = get_url(f"/api/method/api.loyalty.wallet.apple_pass_download?t={quote(token)}")
	return success_response(_("Add to Apple Wallet"), data={"url": url, "expires_in": LINK_TTL_SECONDS})


@frappe.whitelist(allow_guest=True, methods=["GET"])
def apple_pass_download(t: str | None = None):
	"""The .pkpass behind an apple_pass_link URL."""
	if not apple.enabled():
		frappe.throw(_("Apple Wallet is not available."))
	rate_limit_by_caller("loyalty_apple_pass_download", limit=10, seconds=60)
	parts = (t or "").split(".")
	if len(parts) < 3:
		raise frappe.PermissionError(_("This link is invalid."))
	signature, expires = parts[-1], parts[-2]
	account = ".".join(parts[:-2])
	valid = expires.isdigit() and hmac.compare_digest(
		signature.encode(), _link_signature(account, int(expires)).encode()
	)
	if not valid or int(expires) < time.time():
		raise frappe.PermissionError(_("This link has expired. Open your loyalty card again."))
	if frappe.db.get_value("ArcPOS Loyalty Account", account, "status") != "Active":
		raise frappe.PermissionError(_("This loyalty account is not active."))
	_send_pkpass(account)


def _log_rejection(message: str):
	# At most one Error Log a minute: the endpoint is public, and each refusal
	# logged would let anyone fill the table.
	if not frappe.cache().get_value("loyalty:google-callback-rejected"):
		frappe.cache().set_value("loyalty:google-callback-rejected", 1, expires_in_sec=60)
		frappe.log_error(title="Google Wallet callback rejected", message=message)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def google_callback():
	"""Save / delete notifications from Google. Signed by Google, plus our callback token."""
	secret = get_settings().get_password("google_callback_secret", raise_exception=False)
	token = frappe.request.args.get("token") or ""
	# Fails closed: without a secret every caller would be let through to the
	# signature check (and its key fetch).
	if not secret or not hmac.compare_digest(secret.encode(), token.encode()):
		frappe.local.response["http_status_code"] = 401
		return {"ok": False}
	try:
		payload = frappe.parse_json(frappe.request.get_data(as_text=True) or "{}")
		if not isinstance(payload, dict):
			raise google.WalletError("callback body is not a JSON object")
		result = google.handle_callback(payload)
	except google.WalletError as exc:
		_log_rejection(str(exc))
		frappe.local.response["http_status_code"] = 400
		return {"ok": False}
	except Exception:
		# Garbage that broke parsing, or Google's key endpoint being down: a
		# 400 makes Google retry later, a 500 would only fill the logs.
		_log_rejection(frappe.get_traceback())
		frappe.local.response["http_status_code"] = 400
		return {"ok": False}
	frappe.db.commit()
	return {"ok": True, **result}
