"""Validate Sales Invoice items against Item Group visibility rules."""

from excel_restaurant_pos.api.item_group import validate_item_group_visibility


def _get_newly_added_items(doc):
    previous_doc = doc.get_doc_before_save()
    if not previous_doc:
        return []

    previous_row_names = {item.name for item in previous_doc.items if item.name}
    return [
        item
        for item in doc.items
        if not item.name or item.name not in previous_row_names
    ]


def validate_sales_invoice_item_group_visibility_on_insert(doc, method=None):
    if not doc.get("items"):
        return

    validate_item_group_visibility(doc.items)


def validate_sales_invoice_item_group_visibility_on_update(doc, method=None):
    if not doc.get("items"):
        return

    new_items = _get_newly_added_items(doc)
    if new_items:
        validate_item_group_visibility(new_items)
