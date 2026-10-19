# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from excel_restaurant_pos.shared.loyalty.segments import bust_cache


class ArcPOSLoyaltySegment(Document):
	def on_update(self):
		bust_cache()

	def on_trash(self):
		bust_cache()
