# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime

from excel_restaurant_pos.shared.loyalty import campaigns
from excel_restaurant_pos.shared.loyalty.rules import ensure_rule_ids
from excel_restaurant_pos.shared.loyalty.settings import TXN

RULE_FIELDS = (
	"rule_id", "rule_name", "enabled", "trigger", "event_type", "rule_type", "points", "per_amount", "multiplier",
	"multiplier_scope", "applies_to", "min_order_amount", "min_qty", "order_number", "max_points_per_order",
	"condition", "priority", "exclusive",
)
ITEM_FIELDS = ("rule_id", "applies_to", "value")


def _snapshot(doc) -> str:
	return json.dumps(
		{
			"rules": [{k: row.get(k) for k in RULE_FIELDS} for row in doc.get("rules") or []],
			"items": [{k: row.get(k) for k in ITEM_FIELDS} for row in doc.get("rule_items") or []],
		},
		sort_keys=True,
		default=str,
	)


class ArcPOSLoyaltyCampaign(Document):
	def validate(self):
		ensure_rule_ids(self)
		if self.end_datetime and get_datetime(self.end_datetime) < get_datetime(self.start_datetime):
			frappe.throw(_("End cannot be before Start."))
		if self.recurrence == "Weekly" and not campaigns.parse_days(self.recurrence_days):
			frappe.throw(_("Recurrence Days needs weekday names, e.g. Fri,Sat."))
		if self.recurrence == "Yearly" and not self.end_datetime:
			frappe.throw(_("A yearly campaign needs an End to define its window."))
		if frappe.db.get_value("ArcPOS Loyalty Programme", self.programme, "status") == "Ended":
			frappe.throw(_("Programme {0} has ended.").format(self.programme))

		before = self.get_doc_before_save()
		if before and before.status == campaigns.ACTIVE and _snapshot(before) != _snapshot(self):
			frappe.throw(_("Pause the campaign before editing its rules."))

	def on_update(self):
		campaigns.bust_cache(self.programme)

	def on_trash(self):
		if frappe.db.exists(TXN, {"campaign": self.name}):
			frappe.throw(_("This campaign has issued points; end it instead of deleting it."))
		campaigns.bust_cache(self.programme)


@frappe.whitelist(methods=["POST"])
def campaign_action(name, action):
	return campaigns.transition(name, action)


@frappe.whitelist(methods=["POST"])
def duplicate_campaign(name):
	return campaigns.duplicate(name)


@frappe.whitelist(methods=["GET", "POST"])
def simulate_campaign(name, invoice):
	return campaigns.simulate(name, invoice)
