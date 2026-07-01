from .pos_invoice import create_pos_invoice
from .sales_invoice import (
    change_sales_invoice,
    submit_sales_invoice,
    on_update_sales_invoice,
)
from .tax_and_charges import on_doctype_update

__all__ = [
    "create_pos_invoice",
    "change_sales_invoice",
    "submit_sales_invoice",
    "on_update_sales_invoice",
    "on_doctype_update",
]


custom_doc_events = {
    "Sales Invoice": {
        "validate": [
            "excel_restaurant_pos.shared.coupon.services.apply_sales_invoice_coupon_discount",
            "excel_restaurant_pos.shared.coupon.services.validate_sales_invoice_coupon",
        ],
        "before_submit": "excel_restaurant_pos.shared.coupon.services.before_submit_sales_invoice_coupon",
        "on_submit": [
            "excel_restaurant_pos.shared.coupon.services.on_submit_sales_invoice_coupon",
            "excel_restaurant_pos.doc_event.sales_invoice.submit_sales_invoice",
        ],
        "on_trash": "excel_restaurant_pos.doc_event.sales_invoice.on_trash_sales_invoice",
        "on_change": "excel_restaurant_pos.doc_event.sales_invoice.change_sales_invoice",
        "on_update": "excel_restaurant_pos.doc_event.sales_invoice.on_update_sales_invoice",
        "on_update_after_submit": "excel_restaurant_pos.doc_event.sales_invoice.on_update_sales_invoice",
        "after_insert": "excel_restaurant_pos.doc_event.sales_invoice.after_save_sales_invoice",
        "before_insert": [
            "excel_restaurant_pos.doc_event.sales_invoice.before_insert_sales_invoice",
            "excel_restaurant_pos.doc_event.sales_invoice.validate_item_group_visibility.validate_sales_invoice_item_group_visibility_on_insert",
        ],
        "before_save": "excel_restaurant_pos.doc_event.sales_invoice.validate_item_group_visibility.validate_sales_invoice_item_group_visibility_on_update",
    },
    "Sales Taxes and Charges Template": {
        "on_update": "excel_restaurant_pos.doc_event.on_doctype_update",
    },
    "Item Group": {
        "after_insert": "excel_restaurant_pos.doc_event.item_group.clear_visibility_cache.clear_item_group_visibility_cache",
        "on_update": "excel_restaurant_pos.doc_event.item_group.clear_visibility_cache.clear_item_group_visibility_cache",
        "on_trash": "excel_restaurant_pos.doc_event.item_group.clear_visibility_cache.clear_item_group_visibility_cache",
    },
}
