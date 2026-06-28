"""Validate Sales Invoice items against Item Group visibility rules."""

from excel_restaurant_pos.api.item_group.visibility import validate_item_group_visibility


def validate_sales_invoice_item_group_visibility(doc, method=None):
	if not doc.get("items"):
		return

	validate_item_group_visibility(doc.items)
