"""Backfill Coupon Code.custom_order_status from the order that generated it.

The status pair is kept current by the Sales Invoice on_submit / on_cancel
hooks, but coupons created before those hooks existed still carry whatever
custom_order_status they were inserted with. This aligns them with the real
docstatus, and rejects any coupon whose order has since been cancelled.
"""

import frappe

from excel_restaurant_pos.shared.coupon.order_status import (
	COUPON_DOCTYPE,
	LINK_FIELD,
	ORDER_STATUS_CANCELLED,
	ORDER_STATUS_SUBMITTED,
	apply_coupon_order_status,
)


def execute():
	coupons = frappe.get_all(
		COUPON_DOCTYPE,
		filters={LINK_FIELD: ("is", "set")},
		fields=["name", LINK_FIELD],
	)
	if not coupons:
		return

	invoice_names = list({row[LINK_FIELD] for row in coupons if row[LINK_FIELD]})
	docstatus_by_invoice = dict(
		frappe.get_all(
			"Sales Invoice",
			filters={"name": ("in", invoice_names)},
			fields=["name", "docstatus"],
			as_list=True,
		)
	)

	updated = 0
	for row in coupons:
		docstatus = docstatus_by_invoice.get(row[LINK_FIELD])
		# A missing invoice means the order was deleted outright; leave the
		# coupon alone rather than guessing what happened to it.
		if docstatus not in (ORDER_STATUS_SUBMITTED, ORDER_STATUS_CANCELLED):
			continue

		if apply_coupon_order_status(
			row["name"], docstatus, reject=docstatus == ORDER_STATUS_CANCELLED
		):
			updated += 1

	if updated:
		frappe.db.commit()

	print(f"Backfilled custom_order_status on {updated} coupon(s)")
