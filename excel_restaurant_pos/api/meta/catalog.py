import frappe

from .catalog_helpers.create_catalog_item import create_catalog_item
from .catalog_helpers.update_catalog_item import update_catalog_item
from .catalog_helpers.delete_catalog_item import delete_catalog_item


@frappe.whitelist()
def create_catalog_item_api():
    item_code = frappe.form_dict.get("item_code", None)
    if not item_code:
        frappe.throw("Item code is required")
    return create_catalog_item(item_code)


@frappe.whitelist()
def update_catalog_item_api():
    item_code = frappe.form_dict.get("item_code", None)
    if not item_code:
        frappe.throw("Item code is required")
    return update_catalog_item(item_code)


@frappe.whitelist()
def delete_catalog_item_api():
    item_code = frappe.form_dict.get("item_code", None)
    if not item_code:
        frappe.throw("Item code is required")
    return delete_catalog_item(item_code)
