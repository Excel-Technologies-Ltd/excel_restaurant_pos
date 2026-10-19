"""The PassKit web service Apple Wallet calls: /loyalty-wallet/apple/v1/...

Served by a page renderer, because these are REST paths with path parameters
and DELETE, which /api/method cannot express. Two things in Frappe's request
pipeline would refuse Apple's requests before any renderer runs, so
`prepare_request` (a before_request hook, scoped to this prefix only) adjusts
them first:

- frappe.api.validate_auth raises for any two-part Authorization header it
  cannot authenticate as a user -- "ApplePass <token>" included. The header is
  moved to X-ArcPOS-ApplePass, where this module checks it.
- frappe.app routes only GET/HEAD/POST to the website; DELETE is recorded and
  carried as POST.

The guest API rate limiter and CSRF apply to /api/method and session users
only, so neither touches these guest, token-authenticated paths.
"""

from __future__ import annotations

import hmac
import json
import re
from email.utils import format_datetime, parsedate_to_datetime

import frappe
from frappe.utils import cint, get_datetime, now_datetime
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from excel_restaurant_pos.shared.loyalty.settings import DEVICE_REGISTRATION, WALLET_PASS, get_settings
from excel_restaurant_pos.shared.loyalty.wallet import apple
from excel_restaurant_pos.shared.loyalty.wallet.base import render

PREFIX = "loyalty-wallet/apple/"
AUTH_HEADER = "X-ArcPOS-ApplePass"
METHOD_KEY = "arcpos.original_method"

REGISTRATION = re.compile(r"^v1/devices/([^/]+)/registrations/([^/]+)/([^/]+)$")
SERIALS = re.compile(r"^v1/devices/([^/]+)/registrations/([^/]+)$")
PASS = re.compile(r"^v1/passes/([^/]+)/([^/]+)$")
LOG = re.compile(r"^v1/log$")


def prepare_request():
	request = getattr(frappe.local, "request", None)
	if not request or not (request.path or "").lstrip("/").startswith(PREFIX):
		return
	environ = request.environ
	auth = environ.pop("HTTP_AUTHORIZATION", None)
	if auth:
		environ["HTTP_X_ARCPOS_APPLEPASS"] = auth
	environ[METHOD_KEY] = request.method
	if request.method == "DELETE":
		request.method = "POST"


def _respond(status: int, body=None, content_type="application/json", headers=None) -> Response:
	data = body if isinstance(body, (bytes, str)) or body is None else json.dumps(body)
	return Response(data or b"", status=status, content_type=content_type, headers=headers or {})


def _authorised_pass(pass_type: str, serial: str):
	"""The pass when the request carries its ApplePass token, else None."""
	settings = get_settings()
	if not apple.enabled() or pass_type != settings.apple_pass_type_id:
		return None
	header = frappe.get_request_header(AUTH_HEADER) or ""
	scheme, _, token = header.partition(" ")
	if scheme != "ApplePass" or not token:
		return None
	row = frappe.db.get_value(
		WALLET_PASS, {"object_id": serial, "platform": "Apple"}, ["name", "auth_token_hash", "status"], as_dict=True
	)
	if not row or not hmac.compare_digest(row.auth_token_hash or "", apple.hash_token(token.strip())):
		return None
	return row


def _body() -> dict:
	try:
		return json.loads(frappe.request.get_data() or b"{}") or {}
	except ValueError:
		return {}


def _register(device: str, pass_type: str, serial: str) -> Response:
	row = _authorised_pass(pass_type, serial)
	if not row:
		return _respond(401)
	push_token = _body().get("pushToken")
	if not push_token:
		return _respond(400)

	# A pass the member removed and has now added back is live again: left
	# "Removed" it would never be pushed or reconciled.
	if row.status in ("Issued", "Removed"):
		frappe.db.set_value(WALLET_PASS, row.name, "status", "Installed")

	existing = frappe.db.get_value(DEVICE_REGISTRATION, {"device_library_id": device, "pass": row.name}, "name")
	if existing:
		frappe.db.set_value(DEVICE_REGISTRATION, existing, "push_token", push_token)
		return _respond(200)

	frappe.get_doc(
		{
			"doctype": DEVICE_REGISTRATION,
			"device_library_id": device,
			"pass": row.name,
			"serial_number": serial,
			"push_token": push_token,
			"registered_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	return _respond(201)


def _unregister(device: str, pass_type: str, serial: str) -> Response:
	row = _authorised_pass(pass_type, serial)
	if not row:
		return _respond(401)
	names = frappe.get_all(DEVICE_REGISTRATION, filters={"device_library_id": device, "pass": row.name}, pluck="name")
	for name in names:
		frappe.delete_doc(DEVICE_REGISTRATION, name, ignore_permissions=True, force=True)
	if not frappe.db.exists(DEVICE_REGISTRATION, {"pass": row.name}) and row.status == "Installed":
		frappe.db.set_value(WALLET_PASS, row.name, "status", "Removed")
	return _respond(200)


def _stamp(row) -> int:
	return int(get_datetime(row.last_synced_at or row.modified).timestamp())


def _serials(device: str, pass_type: str) -> Response:
	if pass_type != get_settings().apple_pass_type_id:
		return _respond(404)
	since = frappe.form_dict.get("passesUpdatedSince")
	rows = frappe.db.sql(
		f"""
		SELECT p.object_id, p.last_synced_at, p.modified
		FROM `tab{DEVICE_REGISTRATION}` r JOIN `tab{WALLET_PASS}` p ON p.name = r.pass
		WHERE r.device_library_id = %s AND p.platform = 'Apple'
		""",
		device,
		as_dict=True,
	)
	if not rows:
		return _respond(404)
	changed = [row for row in rows if not since or _stamp(row) > cint(since)]
	if not changed:
		return _respond(204)
	return _respond(
		200, {"serialNumbers": [r.object_id for r in changed], "lastUpdated": str(max(_stamp(r) for r in rows))}
	)


def _latest_pass(pass_type: str, serial: str) -> Response:
	row = _authorised_pass(pass_type, serial)
	if not row:
		return _respond(401)
	pass_doc = frappe.get_doc(WALLET_PASS, row.name)
	updated = get_datetime(pass_doc.last_synced_at or pass_doc.modified).replace(microsecond=0)

	since = frappe.get_request_header("If-Modified-Since")
	if since:
		try:
			if updated <= parsedate_to_datetime(since).replace(tzinfo=None):
				return _respond(304)
		except (TypeError, ValueError):
			pass

	data = apple.build_pkpass(render(pass_doc.account), pass_doc)
	return _respond(200, data, "application/vnd.apple.pkpass", {"Last-Modified": format_datetime(updated)})


def _log() -> Response:
	logs = _body().get("logs") or []
	if logs:
		frappe.log_error(title="Apple Wallet device log", message="\n".join(str(line) for line in logs[:50]))
	return _respond(200)


def dispatch(path: str, method: str) -> Response:
	match = REGISTRATION.match(path)
	if match and method == "POST":
		return _register(*match.groups())
	if match and method == "DELETE":
		return _unregister(*match.groups())
	match = SERIALS.match(path)
	if match and method == "GET":
		return _serials(*match.groups())
	match = PASS.match(path)
	if match and method == "GET":
		return _latest_pass(*match.groups())
	if LOG.match(path) and method == "POST":
		return _log()
	return _respond(404)


class AppleWalletWebService(BaseRenderer):
	def can_render(self):
		return self.path.startswith(PREFIX)

	def render(self):
		request = frappe.local.request
		method = request.environ.get(METHOD_KEY) or request.method
		try:
			return dispatch(self.path[len(PREFIX) :], method)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Apple Wallet web service error", message=frappe.get_traceback())
			return _respond(500)
