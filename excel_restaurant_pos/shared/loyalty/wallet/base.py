"""What a wallet pass shows, rendered from the backend. Passes never hold state of their own."""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import cint, flt, fmt_money, get_url, strip_html

from excel_restaurant_pos.shared.loyalty.accounts import member_token
from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, get_programme, get_settings
from excel_restaurant_pos.shared.loyalty.tiers import tier_named

DEFAULT_BACKGROUND = "#1F2937"
DEFAULT_FOREGROUND = "#FFFFFF"
DEFAULT_LABEL = "#D1D5DB"


def absolute(url: str | None) -> str | None:
	if not url:
		return None
	return url if url.startswith("http") else get_url(url)


def render(account_name: str) -> frappe._dict:
	account = frappe.get_doc(ACCOUNT, account_name)
	programme = get_programme(account.programme)
	settings = get_settings()
	currency = frappe.get_cached_value("Company", programme.company, "default_currency") if programme else None
	tier = tier_named(programme, account.tier) if programme else None
	balance = cint(account.available_points)
	value = flt(balance * flt(programme.point_value if programme else 0), 2)

	if account.status == "Closed":
		state = "voided"
	elif account.status == "Suspended" or not programme or programme.status in ("Paused", "Draft"):
		state = "inactive"
	elif programme.status == "Ended":
		state = "expired"
	else:
		state = "active"

	return frappe._dict(
		account=account.name,
		member_number=account.member_number or account.name,
		customer_name=account.customer_name,
		programme=programme.name if programme else None,
		programme_name=(settings.programme_display_name if settings else None)
		or (programme.programme_name if programme else ""),
		programme_end_date=str(programme.end_date) if programme and programme.end_date else None,
		balance=balance,
		value=value,
		value_text=fmt_money(value, currency=currency),
		currency=currency,
		pending=cint(account.pending_points),
		tier=account.tier,
		tier_benefits=(tier.benefits if tier else None),
		next_expiry_date=str(account.next_expiry_date) if account.next_expiry_date else None,
		next_expiry_points=cint(account.next_expiry_points),
		token=member_token(account),
		status=account.status,
		state=state,
		background_color=(tier.pass_color if tier and tier.pass_color else None)
		or (settings.pass_background_color if settings else None)
		or DEFAULT_BACKGROUND,
		foreground_color=(settings.pass_foreground_color if settings else None) or DEFAULT_FOREGROUND,
		label_color=(settings.pass_label_color if settings else None) or DEFAULT_LABEL,
		logo_url=absolute(settings.pass_logo if settings else None),
		icon_url=absolute(settings.pass_icon if settings else None),
		strip_url=absolute(settings.pass_strip_image if settings else None),
		terms=strip_html(programme.terms or "").strip() if programme else "",
	)


def payload_hash(view: dict, platform: str) -> str:
	return hashlib.sha256(json.dumps({"platform": platform, **view}, sort_keys=True, default=str).encode()).hexdigest()


def file_content(file_url: str | None) -> bytes | None:
	"""Bytes of an attached (public or private) file."""
	if not file_url:
		return None
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return None
	content = frappe.get_doc("File", name).get_content()
	return content.encode() if isinstance(content, str) else content
