"""Customer-facing loyalty endpoints (storefront / app, ArcPOS Web Customer).

Every endpoint resolves the account from the session; a customer id from the
client is never accepted. apply_points / remove_points are shared with the
POS: staff may act on any order, a customer only on their own.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from excel_restaurant_pos.api.loyalty.common import account_summary, load_invoice, own_account, require_enabled
from excel_restaurant_pos.shared.customer_access import FULL, access_level, is_staff, require_login
from excel_restaurant_pos.shared.loyalty import accounts, earning, redemption, rewards
from excel_restaurant_pos.shared.loyalty.campaigns import ACTIVE, SCHEDULED, eligible_for, window_open
from excel_restaurant_pos.shared.loyalty.otp import threshold
from excel_restaurant_pos.shared.loyalty.segments import account_segments
from excel_restaurant_pos.shared.loyalty.settings import (
	ACCOUNT,
	CAMPAIGN,
	TXN,
	get_active_programme,
	is_enabled,
	is_excluded_customer,
)
from excel_restaurant_pos.shared.sales_invoice.idempotency import read_key
from excel_restaurant_pos.utils import rate_limit_by_caller
from excel_restaurant_pos.utils.error_handler import success_response

TYPES = ("Earn", "Bonus", "Redeem", "Expire", "Reverse", "Adjust")
MAX_PAGE = 100


@frappe.whitelist(methods=["GET"])
def me():
	customer, account = own_account(required=False)
	if not account:
		return success_response(
			_("Not enrolled"),
			data={"enrolled": False, "can_enrol": bool(get_active_programme()) and not is_excluded_customer(customer)},
		)
	return success_response(_("Loyalty account"), data={"enrolled": True, **account_summary(account)})


@frappe.whitelist(methods=["POST"])
def enrol():
	require_enabled()
	customer, account = own_account(required=False)
	if not account:
		account = accounts.enrol(customer, source="Signup", user=frappe.session.user)
		if not account:
			frappe.throw(_("This account cannot join the loyalty programme."))
		frappe.db.commit()
	return success_response(_("Enrolled"), data={"enrolled": True, **account_summary(account)})


def _source_label(row) -> str | None:
	if row.source_doctype == "Sales Invoice":
		return _("Order {0}").format(row.source_name)
	if row.source_doctype == "Coupon Code":
		return _("Voucher {0}").format(row.source_name)
	if row.event_type:
		return frappe.unscrub(row.event_type)
	if row.source_doctype == "ArcPOS Loyalty Adjustment":
		return _("Adjustment")
	return None


@frappe.whitelist(methods=["GET"])
def transactions(type=None, from_date=None, to_date=None, page=1, page_size=20, **kwargs):
	_customer, account = own_account()
	filters = {"account": account}
	if type:
		wanted = [t for t in str(type).split(",") if t in TYPES]
		if wanted:
			filters["transaction_type"] = ["in", wanted]
	from_date = from_date or kwargs.get("from")
	to_date = to_date or kwargs.get("to")
	if from_date and to_date:
		filters["posting_datetime"] = ["between", [f"{getdate(from_date)} 00:00:00", f"{getdate(to_date)} 23:59:59"]]
	elif from_date:
		filters["posting_datetime"] = [">=", f"{getdate(from_date)} 00:00:00"]
	elif to_date:
		filters["posting_datetime"] = ["<=", f"{getdate(to_date)} 23:59:59"]

	page_size = min(max(cint(page_size) or 20, 1), MAX_PAGE)
	page = max(cint(page) or 1, 1)
	rows = frappe.get_all(
		TXN,
		filters=filters,
		fields=[
			"name",
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
		],
		order_by="posting_datetime desc, name desc",
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
	)
	titles = {}
	for row in rows:
		row["source_label"] = _source_label(row)
		if row.source_doctype == "ArcPOS Loyalty Adjustment":
			# Stored as "<reason>: <staff note>"; the note is internal.
			row["remarks"] = (row.remarks or "").split(":", 1)[0].strip() or _("Adjustment")
		if row.campaign:
			if row.campaign not in titles:
				titles[row.campaign] = frappe.db.get_value(CAMPAIGN, row.campaign, ["title", "campaign_name"], as_dict=True)
			info = titles[row.campaign] or {}
			row["campaign_title"] = info.get("title") or info.get("campaign_name")
		row.pop("source_doctype", None)
	return success_response(
		_("Transactions"), data=rows, page=page, page_size=page_size, total=frappe.db.count(TXN, filters)
	)


@frappe.whitelist(methods=["GET"])
def campaigns():
	_customer, account = own_account()
	programme = get_active_programme()
	if not programme:
		return success_response(_("Campaigns"), data=[])
	member = frappe.db.get_value(ACCOUNT, account, ["tier", "customer"], as_dict=True)
	# Channel-free context: the app lists campaigns, it is not placing an order.
	ctx = {
		"kind": "event",
		"tier": member.tier,
		"segments": account_segments(account),
		"territory": frappe.db.get_value("Customer", member.customer, "territory"),
	}
	out = []
	names = frappe.get_all(
		CAMPAIGN,
		filters={"programme": programme.name, "status": ["in", [ACTIVE, SCHEDULED]], "display_in_app": 1},
		pluck="name",
	)
	for name in names:
		campaign = frappe.get_cached_doc(CAMPAIGN, name)
		if not eligible_for(campaign, ctx):
			continue
		out.append(
			{
				"campaign": campaign.name,
				"title": campaign.title or campaign.campaign_name,
				"description": campaign.description,
				"image": campaign.image,
				"starts": campaign.start_datetime,
				"ends": campaign.end_datetime,
				"recurrence": campaign.recurrence,
				"recurrence_days": campaign.recurrence_days,
				"live_now": campaign.status == ACTIVE and window_open(campaign),
				"upcoming": campaign.status == SCHEDULED,
			}
		)
	return success_response(_("Campaigns"), data=out)


@frappe.whitelist(methods=["GET"])
def rewards_catalogue():
	_customer, account = own_account()
	return success_response(_("Rewards"), data=rewards.list_rewards(account))


@frappe.whitelist(methods=["POST"])
def redeem_reward(reward=None):
	require_enabled()
	rate_limit_by_caller("loyalty_redeem_reward", limit=10, seconds=60)
	_customer, account = own_account()
	request_id = read_key()
	if not request_id:
		frappe.throw(_("An Idempotency-Key header is required."), frappe.ValidationError)
	if not reward:
		frappe.throw(_("reward is required."), frappe.ValidationError)
	result = rewards.redeem_reward(account, reward, request_id)
	frappe.db.commit()
	return success_response(_("Reward redeemed"), data=result)


@frappe.whitelist(methods=["POST"])
def preview_earning(sales_invoice=None, items=None, order_from=None, service_type=None):
	if not is_enabled():
		return success_response(_("Preview"), data={"points": 0, "value": 0, "awards": [], "eligible": False})
	require_login()
	if sales_invoice:
		access_level(sales_invoice)
		data = earning.preview_for_invoice(load_invoice(sales_invoice))
	else:
		customer, _account = own_account(required=False)
		data = earning.preview_for_cart(customer, frappe.parse_json(items) if items else [], order_from, service_type)
	return success_response(_("Preview"), data=data)


def _own_invoice(sales_invoice):
	if access_level(sales_invoice) != FULL:
		frappe.throw(_("This order does not belong to your account."), frappe.PermissionError)
	return load_invoice(sales_invoice)


@frappe.whitelist(methods=["GET"])
def redemption_options(sales_invoice=None):
	require_enabled()
	doc = _own_invoice(sales_invoice)
	data = redemption.options(doc)
	data.pop("account", None)
	data["applied_points"] = cint(doc.get(redemption.POINTS_FIELD))
	data["applied_value"] = redemption.redeemed_value(doc)
	data["step_up_threshold"] = (threshold() or None) if is_staff() else None
	return success_response(_("Redemption options"), data=data)


@frappe.whitelist(methods=["POST"])
def apply_points(sales_invoice=None, points=None):
	require_enabled()
	rate_limit_by_caller("loyalty_apply_points", limit=20, seconds=60)
	_own_invoice(sales_invoice)
	result = redemption.apply_points(sales_invoice, points)
	frappe.db.commit()
	return success_response(_("Points applied"), data=result)


@frappe.whitelist(methods=["POST"])
def remove_points(sales_invoice=None):
	_own_invoice(sales_invoice)
	result = redemption.remove_points(sales_invoice)
	frappe.db.commit()
	return success_response(_("Points removed"), data=result)


@frappe.whitelist(methods=["GET", "POST"])
def preferences(notify_email=None, notify_push=None):
	_customer, account = own_account()
	if frappe.request and frappe.request.method == "POST":
		values = {}
		if notify_email is not None:
			values["notify_email"] = cint(notify_email)
		if notify_push is not None:
			values["notify_push"] = cint(notify_push)
		if values:
			frappe.db.set_value(ACCOUNT, account, values)
			frappe.db.commit()
	prefs = frappe.db.get_value(ACCOUNT, account, ["notify_email", "notify_push"], as_dict=True)
	return success_response(_("Preferences"), data=prefs)
