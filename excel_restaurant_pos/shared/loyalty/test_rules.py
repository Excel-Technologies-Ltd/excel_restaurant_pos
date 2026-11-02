# Copyright (c) 2026, Excel and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.loyalty import rules
from excel_restaurant_pos.shared.loyalty.campaigns import choose_stack


def ctx(**overrides):
	base = {
		"kind": "purchase",
		"channel": "dine_in",
		"weekday": "Fri",
		"hour": 19,
		"order_number": 3,
		"tier": "Bronze",
		"segments": [],
		"order_count": 2,
		"days_since_last_order": 5,
		"total": 113.0,
		"eligible_amount": 100.0,
		"lines": [
			{"item_code": "BURGER", "item_group": "Mains", "item_group_ancestors": ("Food",), "brand": "House", "qty": 2, "amount": 60.0},
			{"item_code": "COLA", "item_group": "Drinks", "item_group_ancestors": ("Beverages",), "brand": "Fizz", "qty": 4, "amount": 40.0},
		],
	}
	base.update(overrides)
	return base


def rule(rule_type="Spend Rate", **fields):
	row = {
		"rule_id": fields.pop("rule_id", rule_type[:4].lower()),
		"rule_name": rule_type,
		"enabled": 1,
		"trigger": "Purchase",
		"rule_type": rule_type,
		"points": 1,
		"per_amount": 1,
		"applies_to": "All Items",
		"priority": 0,
	}
	row.update(fields)
	return row


def base(*rows, items=()):
	return {"scope": "base", "campaign": None, "transaction_type": "Earn", "rules": list(rows), "rule_items": list(items)}


def campaign(name, *rows, items=()):
	return {"scope": name, "campaign": name, "transaction_type": "Bonus", "rules": list(rows), "rule_items": list(items)}


def total(awards):
	return sum(a["points"] for a in awards)


class TestRounding(FrappeTestCase):
	def test_modes(self):
		self.assertEqual(rules.round_points(12.5, "Floor"), 12)
		self.assertEqual(rules.round_points(12.5, "Round"), 13)
		self.assertEqual(rules.round_points(12.1, "Ceil"), 13)
		# Float noise must not cost a point.
		self.assertEqual(rules.round_points(0.1 * 130, "Floor"), 13)
		self.assertEqual(rules.round_points(13.0, "Ceil"), 13)


class TestSpendRules(FrappeTestCase):
	def test_spend_rate_on_eligible_amount(self):
		awards = rules.evaluate(ctx(eligible_amount=99.99), [base(rule(points=1, per_amount=1))])
		self.assertEqual(total(awards), 99)
		self.assertEqual(awards[0]["transaction_type"], "Earn")

	def test_spend_rate_per_ten(self):
		self.assertEqual(total(rules.evaluate(ctx(), [base(rule(points=5, per_amount=10))])), 50)

	def test_threshold_awards_once_at_or_above(self):
		threshold = rule("Spend Threshold", points=25, per_amount=100)
		self.assertEqual(total(rules.evaluate(ctx(eligible_amount=100), [base(threshold)])), 25)
		self.assertEqual(total(rules.evaluate(ctx(eligible_amount=250), [base(threshold)])), 25)
		self.assertEqual(total(rules.evaluate(ctx(eligible_amount=99.99), [base(threshold)])), 0)

	def test_item_quantity_only_matching_lines(self):
		row = rule("Item Quantity", rule_id="qty", points=3, applies_to="Filtered")
		items = [{"rule_id": "qty", "applies_to": "Item", "value": "BURGER"}]
		awards = rules.evaluate(ctx(), [base(row, items=items)])
		self.assertEqual(total(awards), 6)
		self.assertEqual(awards[0]["basis_items"], ["BURGER"])
		self.assertEqual(awards[0]["basis_qty"], 2)

	def test_item_group_matches_ancestors_and_brand(self):
		row = rule("Item Spend", rule_id="grp", points=1, per_amount=1, applies_to="Filtered")
		by_group = [{"rule_id": "grp", "applies_to": "Item Group", "value": "Beverages"}]
		by_brand = [{"rule_id": "grp", "applies_to": "Brand", "value": "House"}]
		self.assertEqual(total(rules.evaluate(ctx(), [base(row, items=by_group)])), 40)
		self.assertEqual(total(rules.evaluate(ctx(), [base(row, items=by_brand)])), 60)

	def test_filtered_rule_without_matching_line_awards_nothing(self):
		row = rule("Fixed Bonus", rule_id="fx", points=10, applies_to="Filtered")
		items = [{"rule_id": "fx", "applies_to": "Item", "value": "DESSERT"}]
		self.assertEqual(total(rules.evaluate(ctx(), [base(row, items=items)])), 0)

	def test_conditions(self):
		self.assertEqual(total(rules.evaluate(ctx(), [base(rule("Fixed Bonus", points=5, min_order_amount=150))])), 0)
		self.assertEqual(total(rules.evaluate(ctx(order_number=1), [base(rule("Fixed Bonus", points=5, order_number=1))])), 5)
		self.assertEqual(total(rules.evaluate(ctx(order_number=2), [base(rule("Fixed Bonus", points=5, order_number=1))])), 0)

	def test_cap_per_order(self):
		self.assertEqual(total(rules.evaluate(ctx(), [base(rule(points=1, max_points_per_order=30))])), 30)

	def test_disabled_rule(self):
		self.assertEqual(total(rules.evaluate(ctx(), [base(rule(enabled=0))])), 0)

	def test_exclusive_stops_lower_priority(self):
		high = rule("Fixed Bonus", rule_id="hi", points=50, priority=10, exclusive=1)
		low = rule(rule_id="lo", points=1, priority=1)
		awards = rules.evaluate(ctx(), [base(high, low)])
		self.assertEqual([a["rule_id"] for a in awards], ["hi"])

	def test_exclusive_only_in_its_scope(self):
		high = rule("Fixed Bonus", rule_id="hi", points=50, priority=10, exclusive=1)
		awards = rules.evaluate(ctx(), [base(rule(rule_id="b")), campaign("C1", high, rule(rule_id="lo", points=1))])
		self.assertEqual(sorted(a["rule_id"] for a in awards), ["b", "hi"])


class TestMultipliers(FrappeTestCase):
	def test_tier_multiplier_on_base_points(self):
		awards = rules.evaluate(ctx(), [base(rule())], tier_multiplier=1.5, tier_name="Gold")
		self.assertEqual(total(awards), 150)
		self.assertTrue(any(a["rule_id"] == "tier-gold" for a in awards))

	def test_campaign_multiplier_base_scope_doubles_base_only(self):
		double = rule("Multiplier", rule_id="x2", multiplier=2, multiplier_scope="Base Points")
		awards = rules.evaluate(ctx(), [base(rule()), campaign("C1", rule("Fixed Bonus", rule_id="fb", points=10), double)])
		bonus = next(a for a in awards if a["rule_id"] == "x2")
		self.assertEqual(bonus["points"], 100)
		self.assertEqual(bonus["transaction_type"], "Bonus")
		self.assertEqual(bonus["campaign"], "C1")
		self.assertEqual(total(awards), 210)

	def test_multiplier_on_all_points(self):
		triple = rule("Multiplier", rule_id="x3", multiplier=3, multiplier_scope="All Points Before Multipliers")
		awards = rules.evaluate(ctx(), [base(rule()), campaign("C1", rule("Fixed Bonus", rule_id="fb", points=10), triple)])
		self.assertEqual(next(a for a in awards if a["rule_id"] == "x3")["points"], 220)


class TestEventRules(FrappeTestCase):
	def test_event_rules_only_fire_for_their_event(self):
		signup = rule("Fixed Bonus", rule_id="su", trigger="Event", event_type="customer_signup", points=5)
		event_ctx = ctx(kind="event", event_code="customer_signup", lines=[], eligible_amount=0)
		self.assertEqual(total(rules.evaluate(event_ctx, [base(signup, rule())])), 5)
		self.assertEqual(total(rules.evaluate(ctx(kind="event", event_code="birthday"), [base(signup)])), 0)
		# A purchase never fires an event rule.
		self.assertEqual(total(rules.evaluate(ctx(), [base(signup)])), 0)


class TestConditions(FrappeTestCase):
	def test_condition_on_plain_values(self):
		row = rule("Fixed Bonus", points=7, condition="order.weekday == 'Fri' and len(order.items) == 2")
		self.assertEqual(total(rules.evaluate(ctx(), [base(row)])), 7)
		self.assertEqual(total(rules.evaluate(ctx(weekday="Mon"), [base(row)])), 0)

	def test_invalid_expression_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			rules.validate_condition("order.total >>> 1")

	def test_no_database_access(self):
		for expression in ("frappe.db.sql('select 1')", "__import__('os').system('true')", "order.__class__"):
			with self.assertRaises(frappe.ValidationError):
				rules.validate_condition(expression)


class TestStacking(FrappeTestCase):
	def test_only_top_non_stackable_survives(self):
		a = frappe._dict(name="A", stackable=0, priority=5, start_datetime="2026-01-01")
		b = frappe._dict(name="B", stackable=0, priority=9, start_datetime="2026-01-01")
		c = frappe._dict(name="C", stackable=1, priority=1, start_datetime="2026-01-01")
		self.assertEqual([x.name for x in choose_stack([a, b, c])], ["B", "C"])


class TestReviewFixes(FrappeTestCase):
	def test_condition_sees_names_inside_generators(self):
		# eval's locals are invisible inside a generator's own scope.
		row = rule("Fixed Bonus", points=5, condition="any(i.qty > order.number for i in order.items)")
		self.assertEqual(total(rules.evaluate(ctx(order_number=3), [base(row)])), 5)

	def test_failing_condition_costs_only_its_rule(self):
		# A first-time member has no days_since_last_order: the comparison
		# raises, and must not take the base points down with it.
		lapsed = rule("Fixed Bonus", rule_id="lapsed", points=50, condition="customer.days_since_last_order > 30")
		awards = rules.evaluate(ctx(days_since_last_order=None), [base(rule(rule_id="spend")), campaign("C1", lapsed)])
		self.assertEqual([a["rule_id"] for a in awards], ["spend"])
		self.assertEqual(total(awards), 100)

	def test_bonuses_round_once(self):
		# 99 at 1 pt per 10 is 9.9 base; x1.5 tier is 14.85 overall -> 14, not 9 + 4.
		spend = rule(points=1, per_amount=10)
		awards = rules.evaluate(ctx(eligible_amount=99.0), [base(spend)], tier_multiplier=1.5, tier_name="Gold")
		self.assertEqual(total(awards), 14)
		double = rule("Multiplier", rule_id="x2", multiplier=2, multiplier_scope="Base Points")
		awards = rules.evaluate(ctx(eligible_amount=99.0), [base(spend), campaign("C1", double)])
		self.assertEqual(total(awards), 19)  # floor(19.8)

	def test_rule_item_may_name_its_rule(self):
		doc = frappe._dict(
			rules=[frappe._dict(idx=1, rule_id=None, rule_name="Burger bonus", rule_type="Item Quantity", trigger="Purchase",
				per_amount=0, multiplier=0, event_type=None, condition=None)],
			rule_items=[frappe._dict(idx=1, rule_id="Burger Bonus", applies_to="Item", value="BURGER")],
		)
		rules.ensure_rule_ids(doc)
		self.assertTrue(doc.rules[0].rule_id)
		self.assertEqual(doc.rule_items[0].rule_id, doc.rules[0].rule_id)
