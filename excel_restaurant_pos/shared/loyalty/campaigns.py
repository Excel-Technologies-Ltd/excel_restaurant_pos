"""Campaigns: windows, recurrence, eligibility, stacking, caps, stats, status."""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, get_time, getdate, now_datetime

from excel_restaurant_pos.shared.loyalty import ledger
from excel_restaurant_pos.shared.loyalty.segments import is_descendant
from excel_restaurant_pos.shared.loyalty.settings import CAMPAIGN, TXN, channel_allowed

DRAFT, SCHEDULED, ACTIVE, PAUSED, ENDED = "Draft", "Scheduled", "Active", "Paused", "Ended"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CACHE_KEY = "loyalty:campaigns:{programme}"


def parse_days(text: str | None) -> set[str]:
	days = set()
	for part in (text or "").replace(";", ",").split(","):
		part = part.strip()[:3].title()
		if part in WEEKDAYS:
			days.add(part)
	return days


def _in_time_window(campaign, at) -> bool:
	start, end = campaign.get("recurrence_start_time"), campaign.get("recurrence_end_time")
	if not start and not end:
		return True
	now = at.time()
	start = get_time(start) if start else get_time("00:00:00")
	end = get_time(end) if end else get_time("23:59:59")
	if start <= end:
		return start <= now <= end
	# An overnight window, e.g. 22:00 -> 02:00.
	return now >= start or now <= end


def _window_day(campaign, at):
	"""The day whose window covers `at`: the small hours of an overnight
	window (Fri 22:00 -> 02:00) belong to the evening it opened on."""
	start, end = campaign.get("recurrence_start_time"), campaign.get("recurrence_end_time")
	if start and end and get_time(start) > get_time(end) and at.time() <= get_time(end):
		return at - timedelta(days=1)
	return at


def _md(value) -> tuple[int, int]:
	return (value.month, value.day)


def window_open(campaign, at=None) -> bool:
	"""Whether the campaign's calendar window covers `at` (ignores status)."""
	at = get_datetime(at or now_datetime())
	start = get_datetime(campaign.get("start_datetime")) if campaign.get("start_datetime") else None
	end = get_datetime(campaign.get("end_datetime")) if campaign.get("end_datetime") else None
	recurrence = campaign.get("recurrence") or "None"

	if start and at < start:
		return False

	if recurrence == "Yearly":
		if campaign.get("recur_until") and at.date() > getdate(campaign.get("recur_until")):
			return False
		if start and end:
			first, last, today = _md(start), _md(end), _md(at)
			inside = first <= today <= last if first <= last else (today >= first or today <= last)
			if not inside:
				return False
		return _in_time_window(campaign, at)

	if end and at > end:
		return False
	if recurrence == "Weekly":
		days = parse_days(campaign.get("recurrence_days"))
		if days and WEEKDAYS[_window_day(campaign, at).weekday()] not in days:
			return False
	if recurrence != "None":
		return _in_time_window(campaign, at)
	return True


def is_finished(campaign, at=None) -> bool:
	at = get_datetime(at or now_datetime())
	if (campaign.get("recurrence") or "None") == "Yearly":
		return bool(campaign.get("recur_until") and at.date() > getdate(campaign.get("recur_until")))
	return bool(campaign.get("end_datetime") and at > get_datetime(campaign.get("end_datetime")))


def _active_names(programme: str) -> list[str]:
	key = CACHE_KEY.format(programme=programme)
	names = frappe.cache().get_value(key)
	if names is None:
		# Scheduled too: the status job runs every 10 minutes, and orders in the
		# first minutes of a window must not miss it. window_open checks the start.
		names = frappe.get_all(
			CAMPAIGN, filters={"programme": programme, "status": ["in", [SCHEDULED, ACTIVE]]}, pluck="name"
		)
		frappe.cache().set_value(key, names, expires_in_sec=600)
	return names


def bust_cache(programme: str | None = None):
	if programme:
		frappe.cache().delete_value(CACHE_KEY.format(programme=programme))


def live_campaigns(programme: str, at=None) -> list:
	at = get_datetime(at or now_datetime())
	out = []
	for name in _active_names(programme):
		try:
			campaign = frappe.get_cached_doc(CAMPAIGN, name)
		except frappe.DoesNotExistError:
			continue
		if campaign.status in (SCHEDULED, ACTIVE) and window_open(campaign, at):
			out.append(campaign)
	return out


def eligible_for(campaign, ctx) -> bool:
	# Event awards have no order channel, so the channel gate only applies to purchases.
	if ctx.get("kind") != "event" and not channel_allowed(campaign, "eligible", ctx.get("channel")):
		return False

	tiers = {t.strip() for t in (campaign.get("eligible_tiers") or "").split(",") if t.strip()}
	if tiers and ctx.get("tier") not in tiers:
		return False

	segments = {row.segment for row in campaign.get("eligible_segments") or []}
	if segments and not segments & set(ctx.get("segments") or []):
		return False

	territories = [row.territory for row in campaign.get("eligible_territories") or []]
	if territories and not any(is_descendant("Territory", ctx.get("territory"), t) for t in territories):
		return False

	budget = cint(campaign.get("points_budget"))
	if budget and issued_points(campaign.name) >= budget:
		return False
	# A member already at the cap must not let this campaign win the
	# non-stackable pick only to award 0, hiding the next-best campaign.
	cap = cint(campaign.get("per_customer_cap"))
	if cap and ctx.get("account") and issued_points(campaign.name, ctx["account"]) >= cap:
		return False
	return True


def select_for_context(programme: str, ctx) -> list:
	"""Live, eligible campaigns; of the non-stackable ones only the top priority survives."""
	eligible = [c for c in live_campaigns(programme, ctx.get("posting_datetime")) if eligible_for(c, ctx)]
	return choose_stack(eligible)


def choose_stack(campaigns) -> list:
	stackable = [c for c in campaigns if cint(c.get("stackable"))]
	exclusive = sorted(
		(c for c in campaigns if not cint(c.get("stackable"))),
		key=lambda c: (-cint(c.get("priority")), get_datetime(c.get("start_datetime")), c.get("name")),
	)
	chosen = stackable + exclusive[:1]
	return sorted(chosen, key=lambda c: (-cint(c.get("priority")), c.get("name")))


def issued_points(campaign: str, account: str | None = None, for_update: bool = False) -> int:
	"""Net points the campaign has given (reversals included), optionally for one member.

	`for_update` reads the latest committed rows: under REPEATABLE READ a
	plain read after the campaign lock would still see this transaction's old
	snapshot and miss what the previous lock holder just awarded.
	"""
	conditions, values = "campaign = %s", [campaign]
	if account:
		conditions += " AND account = %s"
		values.append(account)
	row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(points), 0) FROM `tab{TXN}`
		WHERE {conditions} AND transaction_type IN ('Earn', 'Bonus', 'Reverse')
		{"LOCK IN SHARE MODE" if for_update else ""}
		""",
		values,
	)
	return cint(row[0][0])


def capped_points(campaign_name: str | None, account: str, points: int) -> int:
	"""Clamp an award to the campaign's budget and per-customer cap.

	Takes a short row lock on the campaign only when it has a cap, so
	concurrent orders cannot both spend the last of a budget.
	"""
	if not campaign_name or points <= 0:
		return points
	campaign = frappe.get_cached_doc(CAMPAIGN, campaign_name)
	budget, per_customer = cint(campaign.points_budget), cint(campaign.per_customer_cap)
	if not budget and not per_customer:
		return points

	ledger.lock_row(CAMPAIGN, campaign_name)
	if budget:
		points = min(points, max(budget - issued_points(campaign_name, for_update=True), 0))
	if per_customer:
		points = min(points, max(per_customer - issued_points(campaign_name, account, for_update=True), 0))
	return max(points, 0)


def update_stats(campaign_name: str):
	row = frappe.db.sql(
		f"""
		SELECT
			COALESCE(SUM(points), 0) AS points,
			COUNT(DISTINCT account) AS participants,
			COUNT(DISTINCT CASE WHEN source_doctype = 'Sales Invoice' AND points > 0 THEN source_name END) AS orders
		FROM `tab{TXN}`
		WHERE campaign = %s AND transaction_type IN ('Earn', 'Bonus', 'Reverse')
		""",
		campaign_name,
		as_dict=True,
	)[0]
	frappe.db.set_value(
		CAMPAIGN,
		campaign_name,
		{"points_issued": cint(row.points), "participants": cint(row.participants), "orders": cint(row.orders)},
		update_modified=False,
	)


# ---------------------------------------------------------------- lifecycle


def _set_status(campaign, status, remarks=None):
	previous = campaign.status
	frappe.db.set_value(CAMPAIGN, campaign.name, "status", status)
	campaign.add_comment("Info", _("Status: {0} → {1}. {2}").format(previous, status, remarks or ""))
	bust_cache(campaign.programme)
	frappe.clear_document_cache(CAMPAIGN, campaign.name)


def _scheduled_or_active(campaign) -> str:
	if is_finished(campaign):
		return ENDED
	start = get_datetime(campaign.start_datetime) if campaign.start_datetime else None
	return SCHEDULED if start and now_datetime() < start else ACTIVE


def transition(name: str, action: str) -> str:
	campaign = frappe.get_doc(CAMPAIGN, name)
	campaign.check_permission("write")
	allowed = {
		"activate": (DRAFT,),
		"pause": (ACTIVE, SCHEDULED),
		"resume": (PAUSED,),
		"end": (DRAFT, SCHEDULED, ACTIVE, PAUSED),
	}
	if action not in allowed:
		frappe.throw(_("Unknown campaign action {0}.").format(action))
	if campaign.status not in allowed[action]:
		frappe.throw(_("Cannot {0} a campaign that is {1}.").format(action, campaign.status))

	if action in ("activate", "resume"):
		if not campaign.get("rules"):
			frappe.throw(_("Add at least one rule before activating the campaign."))
		status = _scheduled_or_active(campaign)
	elif action == "pause":
		status = PAUSED
	else:
		status = ENDED

	_set_status(campaign, status)
	return status


def duplicate(name: str) -> str:
	source = frappe.get_doc(CAMPAIGN, name)
	source.check_permission("read")
	copy = frappe.copy_doc(source)
	copy.campaign_name = _("{0} (Copy)").format(source.campaign_name)
	copy.status = DRAFT
	# Rule Items refer to rule ids, so both move to fresh ids together.
	remap = {}
	for row in copy.get("rules") or []:
		remap[row.rule_id] = frappe.generate_hash(length=8)
		row.rule_id = remap[row.rule_id]
	for row in copy.get("rule_items") or []:
		row.rule_id = remap.get(row.rule_id, row.rule_id)
	copy.insert()
	return copy.name


def update_campaign_status():
	"""Every 10 minutes: Scheduled -> Active -> Ended by window, and Ended at budget."""
	for name in frappe.get_all(CAMPAIGN, filters={"status": ["in", [SCHEDULED, ACTIVE]]}, pluck="name"):
		# One broken campaign must not hold up the rest.
		ledger.safely("Loyalty campaign status update failed", _update_status, name)
		frappe.db.commit()


def _update_status(name: str):
	campaign = frappe.get_doc(CAMPAIGN, name)
	target = campaign.status
	if is_finished(campaign):
		target = ENDED
	elif campaign.status == SCHEDULED and campaign.start_datetime and get_datetime(campaign.start_datetime) <= now_datetime():
		target = ACTIVE
	elif cint(campaign.points_budget) and issued_points(campaign.name) >= cint(campaign.points_budget):
		target = ENDED
	if target != campaign.status:
		_set_status(campaign, target, _("by the scheduler"))


def simulate(name: str, invoice: str) -> dict:
	"""Run the rules engine for an existing invoice, as if the campaign were live; writes nothing."""
	from excel_restaurant_pos.shared.loyalty.earning import preview_for_invoice

	campaign = frappe.get_doc(CAMPAIGN, name)
	campaign.check_permission("read")
	return preview_for_invoice(frappe.get_doc("Sales Invoice", invoice), force_campaigns=[campaign])
