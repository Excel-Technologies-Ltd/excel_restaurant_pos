"""Clear the "." some invoices carry as their Order Schedule Type.

Invoices created between late January and early February 2026 were saved with
"." there. It is not one of the field's options, so any later save of such an
invoice -- marking it paid, closing a dine-in order -- fails validation. Empty
means "not set", which is how every reader already treats anything other than
"Scheduled Later".
"""

import frappe


def execute():
	frappe.db.sql(
		"""
		update `tabSales Invoice`
		set custom_order_schedule_type = ''
		where custom_order_schedule_type = '.'
		"""
	)
