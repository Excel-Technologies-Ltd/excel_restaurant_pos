# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ArcPOSLoyaltyTransaction(Document):
	"""One immutable ledger row. Written only by shared/loyalty/ledger.py."""

	def validate(self):
		if not self.is_new():
			frappe.throw(_("Loyalty ledger entries cannot be changed. Post an adjustment instead."))
		if not self.flags.ledger_write:
			frappe.throw(_("Loyalty ledger entries are created by the loyalty service only."))

	def on_trash(self):
		frappe.throw(_("Loyalty ledger entries cannot be deleted."))


def on_doctype_update():
	frappe.db.add_index("ArcPOS Loyalty Transaction", ["account", "status", "expiry_date"])
	frappe.db.add_index("ArcPOS Loyalty Transaction", ["source_doctype", "source_name"])
	frappe.db.add_index("ArcPOS Loyalty Transaction", ["campaign", "posting_datetime"])
	# `reverses` is indexed through search_index in the JSON: an add_index here
	# is dropped by every schema sync and rebuilt straight after.
