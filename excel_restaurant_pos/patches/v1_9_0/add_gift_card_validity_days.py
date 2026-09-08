"""Add Coupon Code.custom_validity_days, the shelf-safe expiry for gift cards.

An Inactive gift card sits unsold for however long it sits. Stamping `valid_upto`
when it is printed starts the clock before anyone owns the card, so a "10 day"
card generated on Monday and sold on Wednesday gives the customer 8 days. The
day count is stored instead and turned into a date at activation.

Created here rather than in fixtures/custom_field.json: that file is generated
by `bench export-fixtures` and hand-editing 900+ records to add one is a poor
trade. The next export will pick this field up like any other.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"Coupon Code": [
		{
			"fieldname": "custom_validity_days",
			"label": "Validity (Days)",
			"fieldtype": "Int",
			"insert_after": "custom_available_balance",
			"non_negative": 1,
			"description": (
				"Days the gift card stays valid, counted from the day it is sold, not "
				"the day it is created. Leave blank to use an explicit Valid Upto date "
				"or the ArcPOS Settings default."
			),
		}
	]
}


def execute():
	if not frappe.db.exists("DocType", "Coupon Code"):
		return

	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	frappe.db.commit()
