"""The rules engine: an order (or event) context in, a list of point awards out.

Pure apart from `frappe.safe_eval`: no database access, so the same code runs
for a real award, a checkout preview and the campaign "Simulate on order"
action. The context is built by earning.py / events.py.

A scope is the programme's base rules or one campaign's rules. Evaluation:

1. Additive rules (Spend Rate, Spend Threshold, Item Quantity, Item Spend,
   Fixed Bonus) per scope, highest priority first; an `exclusive` rule that
   awards stops the lower-priority rules of its scope.
2. The tier multiplier on base points.
3. Multiplier rules, on base points or on everything awarded so far.
4. Rounding per programme, on each award.

A new rule type is one function registered in RULE_HANDLERS plus a Select
option on ArcPOS Loyalty Rule.rule_type.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import frappe
from frappe import _
from frappe.utils import cint, flt

ADDITIVE_TYPES = ("Spend Rate", "Spend Threshold", "Item Quantity", "Item Spend", "Fixed Bonus")
MULTIPLIER = "Multiplier"
PURCHASE, EVENT = "Purchase", "Event"
BASE_SCOPE = "base"

RULE_HANDLERS = {}

EVAL_HELPERS = {"len": len, "sum": sum, "min": min, "max": max, "abs": abs, "any": any, "all": all}


def rule_handler(rule_type):
	def register(fn):
		RULE_HANDLERS[rule_type] = fn
		return fn

	return register


def round_points(value: float, mode: str = "Floor") -> int:
	# The epsilon keeps 12.9999999 (float noise from 0.1 * 130) from flooring to 12.
	value = flt(value)
	if mode == "Ceil":
		return int(math.ceil(value - 1e-9))
	if mode == "Round":
		return int(math.floor(value + 0.5 + 1e-9))
	return int(math.floor(value + 1e-9))


# ---------------------------------------------------------------- matching


def items_by_rule(rule_items) -> dict[str, list[tuple[str, str]]]:
	mapping: dict[str, list[tuple[str, str]]] = {}
	for row in rule_items or []:
		if row.get("rule_id") and row.get("value"):
			mapping.setdefault(row["rule_id"], []).append((row.get("applies_to") or "Item", row["value"]))
	return mapping


def line_matches(line, filters) -> bool:
	for applies_to, value in filters:
		if applies_to == "Item" and line.get("item_code") == value:
			return True
		if applies_to == "Item Group" and (
			line.get("item_group") == value or value in (line.get("item_group_ancestors") or ())
		):
			return True
		if applies_to == "Brand" and line.get("brand") == value:
			return True
	return False


def matching_lines(rule, ctx, filters_by_rule) -> list:
	lines = ctx.get("lines") or []
	if (rule.get("applies_to") or "All Items") != "Filtered":
		return lines
	filters = filters_by_rule.get(rule.get("rule_id")) or []
	return [line for line in lines if line_matches(line, filters)]


# ---------------------------------------------------------------- conditions


def eval_locals(ctx) -> dict:
	# Plain attribute objects, not dicts: on a dict, `order.items` would be the
	# dict's items() method rather than the order lines.
	order = SimpleNamespace(
		total=flt(ctx.get("total")),
		eligible_amount=flt(ctx.get("eligible_amount")),
		channel=ctx.get("channel"),
		weekday=ctx.get("weekday"),
		hour=cint(ctx.get("hour")),
		number=cint(ctx.get("order_number")),
		territory=ctx.get("territory"),
		items=[
			SimpleNamespace(
				item_code=line.get("item_code"),
				item_group=line.get("item_group"),
				brand=line.get("brand"),
				qty=flt(line.get("qty")),
				amount=flt(line.get("amount")),
			)
			for line in ctx.get("lines") or []
		],
	)
	customer = SimpleNamespace(
		tier=ctx.get("tier"),
		order_count=cint(ctx.get("order_count")),
		days_since_last_order=ctx.get("days_since_last_order"),
		segments=list(ctx.get("segments") or []),
	)
	event = SimpleNamespace(code=ctx.get("event_code"), payload=dict(ctx.get("payload") or {}))
	return {"order": order, "customer": customer, "event": event}


def evaluate_condition(expression: str, ctx) -> bool:
	"""Evaluate a rule's custom condition on plain values only -- no docs, no DB."""
	if not (expression or "").strip():
		return True
	# The names go in as globals, not locals: a generator expression runs in a
	# scope of its own that cannot see eval's locals, so
	# `any(i.qty > order.number for i in order.items)` would be a NameError.
	return bool(frappe.safe_eval(expression.strip(), {**EVAL_HELPERS, **eval_locals(ctx)}))


SAMPLE_CONTEXT = {
	"total": 100.0,
	"eligible_amount": 90.0,
	"channel": "dine_in",
	"weekday": "Fri",
	"hour": 19,
	"order_number": 2,
	"territory": "All Territories",
	"lines": [{"item_code": "SAMPLE", "item_group": "Products", "brand": None, "qty": 2, "amount": 90.0}],
	"tier": "Silver",
	"order_count": 1,
	"days_since_last_order": 10,
	"segments": [],
	"event_code": "sample",
	"payload": {},
}


# A first-time member: no previous order, so days_since_last_order is None.
FIRST_ORDER_CONTEXT = {**SAMPLE_CONTEXT, "order_number": 1, "order_count": 0, "days_since_last_order": None, "tier": None}


def validate_condition(expression: str, label: str = ""):
	"""Reject an expression that does not evaluate against a sample order."""
	if not (expression or "").strip():
		return
	try:
		evaluate_condition(expression, SAMPLE_CONTEXT)
	except Exception as exc:
		frappe.throw(_("Invalid condition {0}: {1}").format(label, exc), title=_("Loyalty Rule"))
	try:
		evaluate_condition(expression, FIRST_ORDER_CONTEXT)
	except Exception as exc:
		frappe.msgprint(
			_(
				"Condition {0} fails for a first-time member ({1}), so the rule will not apply to them. "
				"Guard it, e.g. <code>customer.days_since_last_order is not None and ...</code>"
			).format(label, exc),
			title=_("Loyalty Rule"),
			indicator="orange",
		)


def condition_holds(rule, ctx) -> bool:
	"""A rule's condition at award time. One that raises does not match: a bad
	condition must cost its own rule, not every award on the order."""
	try:
		return evaluate_condition(rule.get("condition"), ctx)
	except Exception:
		key = f"loyalty:bad-condition:{rule.get('rule_id')}"
		if not frappe.cache().get_value(key):
			frappe.cache().set_value(key, 1, expires_in_sec=3600)
			frappe.log_error(
				title="Loyalty rule condition failed",
				message=f"Rule {rule.get('rule_id')} ({rule.get('rule_name')}): {rule.get('condition')}\n\n{frappe.get_traceback()}",
			)
		return False


# ---------------------------------------------------------------- handlers


def _amount(rule, ctx, lines) -> float:
	if (rule.get("applies_to") or "All Items") == "Filtered":
		return sum(flt(line.get("amount")) for line in lines)
	return flt(ctx.get("eligible_amount"))


def _per(rule) -> float:
	return flt(rule.get("per_amount")) or 1.0


@rule_handler("Spend Rate")
def spend_rate(rule, ctx, lines):
	amount = _amount(rule, ctx, lines)
	return cint(rule.get("points")) * amount / _per(rule), {"basis_amount": amount}


@rule_handler("Spend Threshold")
def spend_threshold(rule, ctx, lines):
	amount = _amount(rule, ctx, lines)
	if amount <= 0 or amount < flt(rule.get("per_amount")):
		return 0, {}
	return cint(rule.get("points")), {"basis_amount": amount}


@rule_handler("Item Quantity")
def item_quantity(rule, ctx, lines):
	qty = sum(flt(line.get("qty")) for line in lines)
	amount = sum(flt(line.get("amount")) for line in lines)
	return cint(rule.get("points")) * qty, {"basis_qty": qty, "basis_amount": amount}


@rule_handler("Item Spend")
def item_spend(rule, ctx, lines):
	amount = sum(flt(line.get("amount")) for line in lines)
	return cint(rule.get("points")) * amount / _per(rule), {"basis_amount": amount}


@rule_handler("Fixed Bonus")
def fixed_bonus(rule, ctx, lines):
	return cint(rule.get("points")), {"basis_amount": _amount(rule, ctx, lines)}


# ---------------------------------------------------------------- evaluation


def _applies(rule, ctx, lines) -> bool:
	if not cint(rule.get("enabled", 1)):
		return False

	trigger = rule.get("trigger") or PURCHASE
	if ctx.get("kind") == "event":
		if trigger != EVENT or rule.get("event_type") != ctx.get("event_code"):
			return False
	elif trigger != PURCHASE:
		return False

	if (rule.get("applies_to") or "All Items") == "Filtered" and not lines:
		return False
	if flt(rule.get("min_order_amount")) and flt(ctx.get("eligible_amount")) < flt(rule.get("min_order_amount")):
		return False
	if flt(rule.get("min_qty")) and sum(flt(line.get("qty")) for line in lines) < flt(rule.get("min_qty")):
		return False
	if cint(rule.get("order_number")) and cint(ctx.get("order_number")) != cint(rule.get("order_number")):
		return False
	return condition_holds(rule, ctx)


def _ordered(rules):
	return sorted(rules, key=lambda r: (-cint(r.get("priority")), cint(r.get("idx"))))


def _cap(points: float, rule) -> float:
	cap = cint(rule.get("max_points_per_order"))
	return min(points, cap) if cap else points


def _basis_items(rule, lines) -> list | None:
	if (rule.get("applies_to") or "All Items") != "Filtered":
		return None
	return sorted({line.get("item_code") for line in lines if line.get("item_code")})


def evaluate(ctx, scopes, tier_multiplier: float = 1.0, rounding: str = "Floor", tier_name: str | None = None) -> list[dict]:
	"""Awards for an order or event.

	`scopes` is a list of {"scope", "campaign", "transaction_type", "rules",
	"rule_items"}, base scope first. Each award carries scope, campaign,
	rule_id, rule_name, transaction_type, points (int > 0) and the basis used,
	so a partial return can later be reversed pro rata.
	"""
	awards: list[dict] = []
	# Unrounded points per award. A tier bonus or multiplier is the difference
	# between the rounded multiplied total and the rounded total, so the order
	# gets what rounding once at the end would give: 99 at 1 pt per 10 with a
	# x1.5 tier is 9 + 5 = floor(14.85), not 9 + floor(9 x 0.5) = 13.
	raw: list[float] = []

	def uplift(on: float, factor: float) -> int:
		return round_points(on * factor, rounding) - round_points(on, rounding)

	def add(scope, rule_id, rule_name, points, basis=None):
		rounded = round_points(points, rounding)
		if rounded <= 0:
			return False
		awards.append(
			{
				"scope": scope["scope"],
				"campaign": scope.get("campaign"),
				"transaction_type": scope.get("transaction_type") or "Bonus",
				"rule_id": rule_id,
				"rule_name": rule_name,
				"points": rounded,
				**(basis or {}),
			}
		)
		raw.append(flt(points))
		return True

	def total(scope_name=None) -> float:
		return sum(r for a, r in zip(awards, raw) if scope_name is None or a["scope"] == scope_name)

	for scope in scopes:
		filters = items_by_rule(scope.get("rule_items"))
		additive = [r for r in scope.get("rules") or [] if r.get("rule_type") in ADDITIVE_TYPES]
		for rule in _ordered(additive):
			lines = matching_lines(rule, ctx, filters)
			if not _applies(rule, ctx, lines):
				continue
			handler = RULE_HANDLERS.get(rule.get("rule_type"))
			if not handler:
				continue
			points, basis = handler(rule, ctx, lines)
			basis = {**basis, "basis_items": _basis_items(rule, lines)}
			if add(scope, rule.get("rule_id"), rule.get("rule_name"), _cap(points, rule), basis) and cint(rule.get("exclusive")):
				break

	base_points = total(BASE_SCOPE)
	base = next((s for s in scopes if s["scope"] == BASE_SCOPE), None)

	multiplier = flt(tier_multiplier) or 1.0
	if base and base_points and multiplier > 1:
		add(
			base,
			f"tier-{frappe.scrub(tier_name or 'tier')}",
			_("Tier bonus ({0} x{1})").format(tier_name or "", multiplier),
			uplift(base_points, multiplier),
			{"basis_amount": flt(ctx.get("eligible_amount"))},
		)

	before_multipliers = total()
	for scope in scopes:
		filters = items_by_rule(scope.get("rule_items"))
		multipliers = [r for r in scope.get("rules") or [] if r.get("rule_type") == MULTIPLIER]
		for rule in _ordered(multipliers):
			lines = matching_lines(rule, ctx, filters)
			if not _applies(rule, ctx, lines):
				continue
			factor = flt(rule.get("multiplier"))
			if factor <= 1:
				continue
			on = before_multipliers if rule.get("multiplier_scope") == "All Points Before Multipliers" else base_points
			if add(
				scope,
				rule.get("rule_id"),
				rule.get("rule_name"),
				_cap(uplift(on, factor), rule),
				{"basis_amount": flt(ctx.get("eligible_amount"))},
			) and cint(rule.get("exclusive")):
				break

	return awards


def _rows(table) -> list[dict]:
	return [row.as_dict() if hasattr(row, "as_dict") else dict(row) for row in table or []]


def base_scope(programme) -> dict:
	return {
		"scope": BASE_SCOPE,
		"campaign": None,
		"transaction_type": "Earn",
		"rules": _rows(programme.get("base_rules")),
		"rule_items": _rows(programme.get("base_rule_items")),
	}


def campaign_scope(campaign) -> dict:
	return {
		"scope": campaign.name,
		"campaign": campaign.name,
		"transaction_type": "Bonus",
		"rules": _rows(campaign.get("rules")),
		"rule_items": _rows(campaign.get("rule_items")),
	}


def ensure_rule_ids(doc, table="rules", items_table="rule_items"):
	"""Give each rule a stable short id and validate it; Rule Items must point at one."""
	used = set()
	for rule in doc.get(table) or []:
		if not rule.rule_id or rule.rule_id in used:
			rule.rule_id = frappe.generate_hash(length=8)
		used.add(rule.rule_id)
		if rule.rule_type not in RULE_HANDLERS and rule.rule_type != MULTIPLIER:
			frappe.throw(_("Row {0}: unknown rule type {1}.").format(rule.idx, rule.rule_type))
		if rule.rule_type == MULTIPLIER and flt(rule.multiplier) <= 1:
			frappe.throw(_("Row {0}: a Multiplier rule needs a multiplier above 1.").format(rule.idx))
		if rule.rule_type in ("Spend Rate", "Item Spend") and flt(rule.per_amount) <= 0:
			frappe.throw(_("Row {0}: {1} needs Per Amount.").format(rule.idx, rule.rule_type))
		if rule.trigger == EVENT and not rule.event_type:
			frappe.throw(_("Row {0}: an Event rule needs an Event Type.").format(rule.idx))
		validate_condition(rule.condition, _("in rule {0}").format(rule.rule_name or rule.idx))

	# A new rule has no id until this save, so a Rule Item may name its rule by
	# Rule Name instead; it is swapped for the id here.
	by_name = {(rule.rule_name or "").strip().lower(): rule.rule_id for rule in doc.get(table) or [] if rule.rule_name}
	for item in doc.get(items_table) or []:
		if item.rule_id not in used:
			item.rule_id = by_name.get((item.rule_id or "").strip().lower(), item.rule_id)
		if item.rule_id not in used:
			frappe.throw(_("Rule Item row {0} refers to unknown Rule ID {1}.").format(item.idx, item.rule_id))
