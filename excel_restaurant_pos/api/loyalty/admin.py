"""Loyalty setup for POS admin: settings, programmes, campaigns, and the ledger.

Ledger rows (ArcPOS Loyalty Transaction) are written by earning, redemption,
expiry and adjustments. This module lists and reads them. It does not insert
or edit them. Point corrections go through api.loyalty.adjust.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, getdate

from excel_restaurant_pos.api.loyalty.common import account_summary, require_login
from excel_restaurant_pos.api.loyalty.customer import _source_label
from excel_restaurant_pos.shared.loyalty import accounts, campaigns
from excel_restaurant_pos.shared.loyalty.settings import (
	ACCOUNT,
	ADJUSTMENT,
	CAMPAIGN,
	EVENT_TYPE,
	LOYALTY_MANAGER,
	PROGRAMME,
	REWARD,
	SEGMENT,
	SETTINGS,
	TIER_CHANGE,
	TXN,
)
from excel_restaurant_pos.utils.error_handler import success_response

MANAGERS = (LOYALTY_MANAGER, "System Manager")
MAX_PAGE = 100
SKIP = {"cmd", "data"}
LAYOUT = {"Section Break", "Column Break", "Tab Break", "Fold"}
PROGRAMME_STATUS = {
	"draft": "Draft",
	"active": "Active",
	"inactive": "Paused",
	"paused": "Paused",
	"ended": "Ended",
}
ACCOUNT_STATUS = {"active": "Active", "inactive": "Suspended", "suspended": "Suspended", "closed": "Closed"}

PROGRAMME_FIELDS = (
	"programme_name",
	"company",
	"status",
	"start_date",
	"end_date",
	"points_rounding",
	"earn_basis",
	"earn_on",
	"pending_days",
	"exclude_gift_card_items",
	"earn_on_loyalty_paid_amount",
	"earn_dine_in",
	"earn_in_store_pickup",
	"earn_online_delivery",
	"earn_online_pickup",
	"point_value",
	"min_redeem_points",
	"max_redeem_points_per_order",
	"max_redeem_percent_of_order",
	"redeem_increment",
	"allow_negative_balance_on_reversal",
	"restore_grace_days",
	"redeem_dine_in",
	"redeem_in_store_pickup",
	"redeem_online_delivery",
	"redeem_online_pickup",
	"expiry_mode",
	"expiry_days",
	"expiry_notice_days",
	"tier_basis",
	"tier_review",
	"terms",
)
PROGRAMME_TABLES = ("exclude_item_groups", "base_rules", "base_rule_items", "tiers")

SETTINGS_FIELDS = (
	"enabled",
	"active_programme",
	"auto_enrol_on_signup",
	"auto_enrol_on_first_order",
	"adjustment_approval_threshold",
	"step_up_threshold_points",
	"refund_expired_vouchers",
	"notify_email",
	"notify_push",
	"loyalty_mode_of_payment",
	"liability_account",
	"expense_account",
	"cost_center",
	"liability_true_up_frequency",
	"voucher_pricing_rule",
	"email_template_earned",
	"email_template_redeemed",
	"email_template_expiring",
	"email_template_tier",
	"email_template_voucher",
	"email_template_otp",
	"google_enabled",
	"google_issuer_id",
	"google_class_suffix",
	"google_origins",
	"google_service_account_json",
	"apple_enabled",
	"apple_pass_type_id",
	"apple_team_id",
	"apple_organization_name",
	"apple_web_service_url",
	"apple_apns_environment",
	"apple_pass_certificate",
	"apple_wwdr_certificate",
	"programme_display_name",
	"pass_logo",
	"pass_icon",
	"pass_strip_image",
	"pass_background_color",
	"pass_foreground_color",
	"pass_label_color",
)
SETTINGS_TABLES = ("excluded_customers",)

CAMPAIGN_FIELDS = (
	"campaign_name",
	"programme",
	"priority",
	"stackable",
	"display_in_app",
	"start_datetime",
	"end_datetime",
	"recurrence",
	"recurrence_days",
	"recurrence_start_time",
	"recurrence_end_time",
	"recur_until",
	"eligible_dine_in",
	"eligible_in_store_pickup",
	"eligible_online_delivery",
	"eligible_online_pickup",
	"eligible_tiers",
	"points_budget",
	"per_customer_cap",
	"title",
	"image",
	"description",
)
CAMPAIGN_TABLES = ("rules", "rule_items", "eligible_segments", "eligible_territories")

REWARD_FIELDS = (
	"reward_name",
	"programme",
	"enabled",
	"reward_type",
	"points_cost",
	"image",
	"description",
	"discount_type",
	"discount_value",
	"max_discount_amount",
	"free_item",
	"voucher_validity_days",
	"redemption_allow_on",
	"min_order_amount",
	"eligible_tiers",
	"stock_limit",
	"per_customer_limit",
	"active_from",
	"active_to",
)

SEGMENT_FIELDS = (
	"segment_name",
	"match_mode",
	"description",
	"customer_group",
	"territory",
	"tier",
	"min_lifetime_spend",
	"enrolled_from",
	"enrolled_to",
	"min_orders",
	"max_orders",
	"last_order_within_days",
)
SEGMENT_TABLES = ("members",)

EVENT_FIELDS = ("event_code", "enabled", "description", "once_per_customer", "cooldown_days")


def require_manager() -> str:
	"""Loyalty Manager or System Manager. Cashiers keep the till routes only."""
	user = require_login()
	if user == "Administrator":
		return user
	if not set(frappe.get_roles(user)) & set(MANAGERS):
		frappe.throw(_("You are not permitted to manage the loyalty programme."), frappe.PermissionError)
	return user


def _data(data=None, **kwargs) -> dict:
	if data not in (None, ""):
		parsed = frappe.parse_json(data) if isinstance(data, str) else data
		return dict(parsed or {})
	return {key: value for key, value in kwargs.items() if key not in SKIP}


def _paging(page=1, page_size=20):
	page_size = min(max(cint(page_size) or 20, 1), MAX_PAGE)
	page = max(cint(page) or 1, 1)
	return page, page_size, (page - 1) * page_size


def _listed(doctype, filters, fields, order_by, page=1, page_size=20, or_filters=None):
	page, page_size, start = _paging(page, page_size)
	rows = frappe.get_all(
		doctype,
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by=order_by,
		limit_start=start,
		limit_page_length=page_size,
	)
	total = len(frappe.get_all(doctype, filters=filters, or_filters=or_filters, pluck="name"))
	return success_response(_("Records"), data=rows, page=page, page_size=page_size, total=total)


def _load(doctype, name):
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} was not found.").format(doctype, name or ""), frappe.DoesNotExistError)
	return frappe.get_doc(doctype, name)


def _clean(meta, row: dict) -> dict:
	out = {}
	for key, value in row.items():
		field = meta.get_field(key) if meta else None
		if field and field.fieldtype in LAYOUT | {"Password"}:
			continue
		if field and field.fieldtype == "Table" and isinstance(value, list):
			child = frappe.get_meta(field.options)
			out[key] = [_clean(child, item) for item in value]
			continue
		if key in ("owner", "creation", "modified", "modified_by", "docstatus", "idx", "parent", "parentfield", "parenttype"):
			continue
		out[key] = value
	if row.get("name"):
		out["name"] = row["name"]
	return out


def _public(doc) -> dict:
	return _clean(doc.meta, doc.as_dict())


def _child_fields(parent_meta, table: str) -> set[str]:
	options = parent_meta.get_field(table).options
	return {
		field.fieldname
		for field in frappe.get_meta(options).fields
		if field.fieldtype not in LAYOUT
	}


def _apply(doc, data: dict, fields, tables=()) -> bool:
	touched = False
	for field in fields:
		if field in data:
			doc.set(field, data[field])
			touched = True
	for table in tables:
		if table not in data:
			continue
		rows = data[table] or []
		if isinstance(rows, str):
			rows = frappe.parse_json(rows)
		allowed = _child_fields(doc.meta, table)
		doc.set(table, [])
		for row in rows:
			if isinstance(row, str):
				row = frappe.parse_json(row)
			doc.append(table, {key: value for key, value in (row or {}).items() if key in allowed})
		touched = True
	return touched


def _save_new(doctype, data, fields, tables=()):
	doc = frappe.new_doc(doctype)
	if not _apply(doc, data, fields, tables):
		frappe.throw(_("Send the fields to create."))
	doc.insert()
	frappe.db.commit()
	return doc


def _save_existing(doctype, name, data, fields, tables=()):
	doc = _load(doctype, name)
	if not _apply(doc, data, fields, tables):
		frappe.throw(_("Nothing to update."))
	doc.save()
	frappe.db.commit()
	return doc


def _mapped(value, mapping: dict, label: str) -> str:
	mapped = mapping.get(str(value or "").strip().lower())
	if not mapped:
		frappe.throw(_("{0} must be one of: {1}.").format(label, ", ".join(sorted(set(mapping.values())))))
	return mapped


# ---------------------------------------------------------------- settings


@frappe.whitelist(methods=["GET"])
def get_settings():
	"""Current Loyalty Settings. Secrets (token, certificate password) are omitted."""
	require_manager()
	return success_response(_("Loyalty settings"), data=_public(frappe.get_doc(SETTINGS)))


@frappe.whitelist(methods=["POST"])
def update_settings(data=None, **kwargs):
	require_manager()
	doc = _save_existing(SETTINGS, SETTINGS, _data(data, **kwargs), SETTINGS_FIELDS, SETTINGS_TABLES)
	return success_response(_("Loyalty settings updated"), data=_public(doc))


# ---------------------------------------------------------------- programme


def _programme_payload(data=None, **kwargs) -> dict:
	payload = _data(data, **kwargs)
	if "status" in payload:
		payload["status"] = _mapped(payload["status"], PROGRAMME_STATUS, "Status")
	return payload


@frappe.whitelist(methods=["GET"])
def list_programmes(status=None, company=None, page=1, page_size=20):
	require_manager()
	filters = {}
	if status:
		filters["status"] = _mapped(status, PROGRAMME_STATUS, "Status")
	if company:
		filters["company"] = company
	return _listed(
		PROGRAMME,
		filters,
		["name", "programme_name", "company", "status", "start_date", "end_date", "point_value"],
		"modified desc",
		page,
		page_size,
	)


@frappe.whitelist(methods=["GET"])
def get_programme(name=None):
	require_manager()
	return success_response(_("Programme"), data=_public(_load(PROGRAMME, name)))


@frappe.whitelist(methods=["POST"])
def create_programme(data=None, **kwargs):
	"""Create a programme. status Active is refused while another programme for the company is Active."""
	require_manager()
	doc = _save_new(PROGRAMME, _programme_payload(data, **kwargs), PROGRAMME_FIELDS, PROGRAMME_TABLES)
	return success_response(_("Programme created"), data=_public(doc))


@frappe.whitelist(methods=["POST"])
def update_programme(name=None, data=None, **kwargs):
	require_manager()
	doc = _save_existing(PROGRAMME, name, _programme_payload(data, **kwargs), PROGRAMME_FIELDS, PROGRAMME_TABLES)
	return success_response(_("Programme updated"), data=_public(doc))


@frappe.whitelist(methods=["POST"])
def set_programme_status(name=None, status=None):
	"""Active, Paused (also accepted as inactive), Draft or Ended. One Active programme per company."""
	require_manager()
	doc = _load(PROGRAMME, name)
	doc.status = _mapped(status, PROGRAMME_STATUS, "Status")
	doc.save()
	frappe.db.commit()
	return success_response(_("Programme {0}").format(doc.status.lower()), data=_public(doc))


# ---------------------------------------------------------------- transactions (read only)


def _txn_filters(account=None, customer=None, programme=None, type=None, status=None, from_date=None, to_date=None):
	filters = {}
	if account:
		filters["account"] = account
	if customer:
		filters["customer"] = customer
	if programme:
		filters["programme"] = programme
	if status:
		filters["status"] = status
	if type:
		wanted = [part.strip() for part in str(type).split(",") if part.strip()]
		if wanted:
			filters["transaction_type"] = ["in", wanted]
	if from_date and to_date:
		filters["posting_datetime"] = ["between", [f"{getdate(from_date)} 00:00:00", f"{getdate(to_date)} 23:59:59"]]
	elif from_date:
		filters["posting_datetime"] = [">=", f"{getdate(from_date)} 00:00:00"]
	elif to_date:
		filters["posting_datetime"] = ["<=", f"{getdate(to_date)} 23:59:59"]
	return filters


TXN_FIELDS = [
	"name",
	"account",
	"customer",
	"programme",
	"posting_datetime",
	"transaction_type",
	"points",
	"status",
	"available_on",
	"expiry_date",
	"remaining_points",
	"source_doctype",
	"source_name",
	"campaign",
	"event_type",
	"remarks",
	"currency_value",
]


@frappe.whitelist(methods=["GET"])
def list_transactions(
	account=None, customer=None, programme=None, type=None, status=None, from_date=None, to_date=None, page=1, page_size=20
):
	require_manager()
	filters = _txn_filters(account, customer, programme, type, status, from_date, to_date)
	page, page_size, start = _paging(page, page_size)
	rows = frappe.get_all(
		TXN,
		filters=filters,
		fields=TXN_FIELDS,
		order_by="posting_datetime desc, name desc",
		limit_start=start,
		limit_page_length=page_size,
	)
	for row in rows:
		row["source_label"] = _source_label(row)
	return success_response(
		_("Transactions"), data=rows, page=page, page_size=page_size, total=frappe.db.count(TXN, filters)
	)


@frappe.whitelist(methods=["GET"])
def get_transaction(name=None):
	require_manager()
	doc = _load(TXN, name)
	data = _public(doc)
	data["source_label"] = _source_label(doc)
	return success_response(_("Transaction"), data=data)


# ---------------------------------------------------------------- accounts


@frappe.whitelist(methods=["GET"])
def list_accounts(status=None, programme=None, query=None, page=1, page_size=20):
	require_manager()
	filters = {}
	if status:
		filters["status"] = _mapped(status, ACCOUNT_STATUS, "Status")
	if programme:
		filters["programme"] = programme
	or_filters = None
	if query:
		like = f"%{query}%"
		or_filters = [["member_number", "like", like], ["customer_name", "like", like], ["customer", "like", like]]
	return _listed(
		ACCOUNT,
		filters,
		["name", "member_number", "customer", "customer_name", "status", "tier", "available_points", "pending_points", "programme"],
		"modified desc",
		page,
		page_size,
		or_filters,
	)


@frappe.whitelist(methods=["GET"])
def get_account(name=None):
	require_manager()
	doc = _load(ACCOUNT, name)
	data = account_summary(doc.name, include_token=False)
	data.update(
		{
			"name": doc.name,
			"customer": doc.customer,
			"programme_id": doc.programme,
			"enrolment_source": doc.enrolment_source,
			"order_count": cint(doc.order_count),
			"qualifying_value": doc.qualifying_value,
		}
	)
	return success_response(_("Loyalty account"), data=data)


@frappe.whitelist(methods=["POST"])
def set_account_status(name=None, status=None, remarks=None):
	"""Active, Suspended (also accepted as inactive) or Closed. A closed account stays closed."""
	require_manager()
	accounts.set_status(name, _mapped(status, ACCOUNT_STATUS, "Status"), remarks)
	frappe.db.commit()
	return success_response(_("Account updated"), data=account_summary(name, include_token=False))


# ---------------------------------------------------------------- campaigns, rewards, segments, events


@frappe.whitelist(methods=["GET"])
def list_campaigns(programme=None, status=None, page=1, page_size=20):
	require_manager()
	filters = {}
	if programme:
		filters["programme"] = programme
	if status:
		filters["status"] = status
	return _listed(
		CAMPAIGN,
		filters,
		["name", "campaign_name", "programme", "status", "start_datetime", "end_datetime", "points_issued", "title"],
		"modified desc",
		page,
		page_size,
	)


@frappe.whitelist(methods=["GET"])
def get_campaign(name=None):
	require_manager()
	return success_response(_("Campaign"), data=_public(_load(CAMPAIGN, name)))


@frappe.whitelist(methods=["POST"])
def create_campaign(data=None, **kwargs):
	require_manager()
	doc = _save_new(CAMPAIGN, _data(data, **kwargs), CAMPAIGN_FIELDS, CAMPAIGN_TABLES)
	return success_response(_("Campaign created"), data=_public(doc))


@frappe.whitelist(methods=["POST"])
def update_campaign(name=None, data=None, **kwargs):
	"""Rules of a live campaign cannot be edited. Pause it first. Status changes use campaign_action."""
	require_manager()
	payload = _data(data, **kwargs)
	payload.pop("status", None)
	doc = _save_existing(CAMPAIGN, name, payload, CAMPAIGN_FIELDS, CAMPAIGN_TABLES)
	return success_response(_("Campaign updated"), data=_public(doc))


@frappe.whitelist(methods=["POST"])
def campaign_action(name=None, action=None):
	"""action: activate, pause, resume, end."""
	require_manager()
	status = campaigns.transition(name, action)
	frappe.db.commit()
	return success_response(_("Campaign {0}").format(status.lower()), data={"name": name, "status": status})


@frappe.whitelist(methods=["GET"])
def list_rewards(programme=None, enabled=None, page=1, page_size=20):
	require_manager()
	filters = {}
	if programme:
		filters["programme"] = programme
	if enabled not in (None, ""):
		filters["enabled"] = cint(enabled)
	return _listed(
		REWARD,
		filters,
		["name", "reward_name", "programme", "enabled", "reward_type", "points_cost", "redeemed_count"],
		"modified desc",
		page,
		page_size,
	)


@frappe.whitelist(methods=["GET"])
def get_reward(name=None):
	require_manager()
	return success_response(_("Reward"), data=_public(_load(REWARD, name)))


@frappe.whitelist(methods=["POST"])
def create_reward(data=None, **kwargs):
	require_manager()
	doc = _save_new(REWARD, _data(data, **kwargs), REWARD_FIELDS)
	return success_response(_("Reward created"), data=_public(doc))


@frappe.whitelist(methods=["POST"])
def update_reward(name=None, data=None, **kwargs):
	require_manager()
	doc = _save_existing(REWARD, name, _data(data, **kwargs), REWARD_FIELDS)
	return success_response(_("Reward updated"), data=_public(doc))


@frappe.whitelist(methods=["GET"])
def list_segments(page=1, page_size=20):
	require_manager()
	return _listed(SEGMENT, {}, ["name", "segment_name", "match_mode", "tier", "customer_group"], "modified desc", page, page_size)


@frappe.whitelist(methods=["GET"])
def get_segment(name=None):
	require_manager()
	return success_response(_("Segment"), data=_public(_load(SEGMENT, name)))


@frappe.whitelist(methods=["POST"])
def create_segment(data=None, **kwargs):
	require_manager()
	doc = _save_new(SEGMENT, _data(data, **kwargs), SEGMENT_FIELDS, SEGMENT_TABLES)
	return success_response(_("Segment created"), data=_public(doc))


@frappe.whitelist(methods=["POST"])
def update_segment(name=None, data=None, **kwargs):
	require_manager()
	doc = _save_existing(SEGMENT, name, _data(data, **kwargs), SEGMENT_FIELDS, SEGMENT_TABLES)
	return success_response(_("Segment updated"), data=_public(doc))


@frappe.whitelist(methods=["GET"])
def list_event_types(page=1, page_size=50):
	require_manager()
	return _listed(
		EVENT_TYPE,
		{},
		["name", "event_code", "enabled", "once_per_customer", "cooldown_days", "is_builtin"],
		"event_code asc",
		page,
		page_size,
	)


@frappe.whitelist(methods=["GET"])
def get_event_type(name=None):
	require_manager()
	return success_response(_("Event type"), data=_public(_load(EVENT_TYPE, name)))


@frappe.whitelist(methods=["POST"])
def create_event_type(data=None, **kwargs):
	require_manager()
	doc = _save_new(EVENT_TYPE, _data(data, **kwargs), EVENT_FIELDS)
	return success_response(_("Event type created"), data=_public(doc))


@frappe.whitelist(methods=["POST"])
def update_event_type(name=None, data=None, **kwargs):
	require_manager()
	doc = _load(EVENT_TYPE, name)
	payload = _data(data, **kwargs)
	if cint(doc.is_builtin):
		payload.pop("event_code", None)
	if not _apply(doc, payload, EVENT_FIELDS):
		frappe.throw(_("Nothing to update."))
	doc.save()
	frappe.db.commit()
	return success_response(_("Event type updated"), data=_public(doc))


# ---------------------------------------------------------------- adjustments and tier history


@frappe.whitelist(methods=["GET"])
def list_adjustments(account=None, approval_status=None, page=1, page_size=20):
	require_manager()
	filters = {}
	if account:
		filters["account"] = account
	if approval_status:
		filters["approval_status"] = approval_status
	return _listed(
		ADJUSTMENT,
		filters,
		["name", "account", "points", "reason", "approval_status", "docstatus", "requested_by", "creation"],
		"creation desc",
		page,
		page_size,
	)


@frappe.whitelist(methods=["GET"])
def get_adjustment(name=None):
	require_manager()
	return success_response(_("Adjustment"), data=_public(_load(ADJUSTMENT, name)))


@frappe.whitelist(methods=["POST"])
def approve_adjustment(name=None):
	require_manager()
	from excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_adjustment.arcpos_loyalty_adjustment import (
		approve,
	)

	approve(name)
	frappe.db.commit()
	return success_response(_("Adjustment posted"), data=_public(_load(ADJUSTMENT, name)))


@frappe.whitelist(methods=["POST"])
def reject_adjustment(name=None, reason=None):
	require_manager()
	from excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_adjustment.arcpos_loyalty_adjustment import (
		reject,
	)

	reject(name, reason)
	frappe.db.commit()
	return success_response(_("Adjustment rejected"), data=_public(_load(ADJUSTMENT, name)))


@frappe.whitelist(methods=["GET"])
def list_tier_changes(account=None, page=1, page_size=20):
	require_manager()
	filters = {"account": account} if account else {}
	return _listed(
		TIER_CHANGE,
		filters,
		["name", "account", "customer", "from_tier", "to_tier", "reason", "changed_at"],
		"changed_at desc",
		page,
		page_size,
	)
