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
            "excel_restaurant_pos.shared.gift_card.services.validate_gift_card_lines",
            "excel_restaurant_pos.shared.gift_card.redemption.apply_sales_invoice_gift_card_discount",
            "excel_restaurant_pos.shared.gift_card.redemption.validate_sales_invoice_gift_card_redemption",
            # ERPNext's own loyalty would issue points a second time.
            "excel_restaurant_pos.shared.loyalty.disable_native_loyalty",
            "excel_restaurant_pos.shared.loyalty.rewards.validate_free_item_vouchers",
            # After the coupon and gift card discounts: points are capped
            # against the total those leave.
            "excel_restaurant_pos.shared.loyalty.redemption.validate_invoice_redemption",
            "excel_restaurant_pos.doc_event.sales_invoice.sync_item_status_with_order_status",
            # Runs last: the coupon discount and grand total are settled by now.
            "excel_restaurant_pos.doc_event.sales_invoice.validate_non_zero_grand_total",
        ],
        "before_submit": [
            "excel_restaurant_pos.shared.coupon.services.before_submit_sales_invoice_coupon",
            "excel_restaurant_pos.shared.gift_card.services.process_gift_cards_on_submit",
            # Spends the points under the account lock, inside the submit.
            "excel_restaurant_pos.shared.loyalty.redemption.post_redemption",
        ],
        "on_submit": [
            "excel_restaurant_pos.shared.coupon.services.on_submit_sales_invoice_coupon",
            "excel_restaurant_pos.shared.gift_card.services.finalize_gift_card_links",
            "excel_restaurant_pos.shared.gift_card.services.record_gift_card_redemptions",
            "excel_restaurant_pos.doc_event.sales_invoice.submit_sales_invoice",
            # Stamps custom_order_status = 1 on coupons generated on this order.
            "excel_restaurant_pos.shared.coupon.order_status.on_submit_sales_invoice_coupon_status",
            # Books the points tender first, so an order the points paid in
            # full is already Paid when earning looks at it.
            "excel_restaurant_pos.shared.loyalty.redemption.on_submit_redemption",
            "excel_restaurant_pos.shared.loyalty.earning.on_invoice_submit",
            "excel_restaurant_pos.shared.loyalty.reversal.on_return_submit",
            "excel_restaurant_pos.shared.gift_card.reversal.on_return_submit",
        ],
        "before_cancel": [
            # Before ERPNext unlinks the invoice's Payment Entries on cancel.
            "excel_restaurant_pos.shared.loyalty.reversal.before_invoice_cancel",
        ],
        "on_cancel": [
            # custom_order_status = 2 and custom_status = Rejected, so a coupon
            # from a voided order cannot be spent.
            "excel_restaurant_pos.shared.coupon.order_status.on_cancel_sales_invoice_coupon_status",
            # Gives back what the order spent from gift cards.
            "excel_restaurant_pos.shared.gift_card.reversal.on_invoice_cancel",
            "excel_restaurant_pos.shared.loyalty.reversal.on_invoice_cancel",
        ],
        "on_trash": "excel_restaurant_pos.doc_event.sales_invoice.on_trash_sales_invoice",
        "on_change": "excel_restaurant_pos.doc_event.sales_invoice.change_sales_invoice",
        "on_update": "excel_restaurant_pos.doc_event.sales_invoice.on_update_sales_invoice",
        "before_update_after_submit": "excel_restaurant_pos.doc_event.sales_invoice.sync_item_status_with_order_status",
        "on_update_after_submit": "excel_restaurant_pos.doc_event.sales_invoice.on_update_sales_invoice",
        "after_insert": [
            "excel_restaurant_pos.doc_event.sales_invoice.after_save_sales_invoice",
            "excel_restaurant_pos.shared.client_contact.create_client_contact_from_invoice",
        ],
        "before_insert": [
            "excel_restaurant_pos.doc_event.sales_invoice.before_insert_sales_invoice",
            "excel_restaurant_pos.doc_event.sales_invoice.validate_item_group_visibility.validate_sales_invoice_item_group_visibility_on_insert",
        ],
        "before_save": "excel_restaurant_pos.doc_event.sales_invoice.validate_item_group_visibility.validate_sales_invoice_item_group_visibility_on_update",
    },
    "Sales Taxes and Charges Template": {
        "on_update": "excel_restaurant_pos.doc_event.on_doctype_update",
    },
    "Payment Entry": {
        # ERPNext sets Sales Invoice.status to Paid with db_set, which fires no
        # doc events, so the invoice itself cannot tell us a payment landed.
        "on_submit": [
            "excel_restaurant_pos.doc_event.payment_entry.settle_order_status_on_payment",
            "excel_restaurant_pos.shared.loyalty.earning.on_payment_settled",
        ],
        # A points tender cancelled on its own gives the points back.
        "on_cancel": "excel_restaurant_pos.shared.loyalty.reversal.on_payment_cancel",
    },
    "Coupon Code": {
        "after_insert": "excel_restaurant_pos.shared.client_contact.create_client_contact_from_coupon",
        # on_update fires on insert as well, so it covers both create and update.
        # Registering after_insert too would generate the codes twice per insert.
        "on_update": [
            "excel_restaurant_pos.shared.coupon.ensure_coupon_codes",
            # An unused loyalty reward voucher that expires refunds its points.
            "excel_restaurant_pos.shared.loyalty.rewards.on_voucher_status_change",
        ],
    },
    "ArcPOS Feedback": {
        # Feedback rows are created at submit and completed later, so the
        # event is the completion, not the insert.
        "on_update": "excel_restaurant_pos.shared.loyalty.events.on_feedback_update",
    },
    "Customer": {
        "after_insert": "excel_restaurant_pos.shared.client_contact.create_client_contact_from_customer",
    },
    "Contact": {
        # on_update covers insert too. create_customer attaches the Contact after
        # the Customer exists, so this is where the email/phone actually arrives.
        "on_update": "excel_restaurant_pos.shared.client_contact.sync_client_contact_from_contact",
    },
    "Item": {
        # The search term index is a snapshot of item names, codes and groups.
        "after_insert": "excel_restaurant_pos.doc_event.item.clear_search_index.clear_item_search_index_cache",
        "on_update": "excel_restaurant_pos.doc_event.item.clear_search_index.clear_item_search_index_cache",
        "on_trash": "excel_restaurant_pos.doc_event.item.clear_search_index.clear_item_search_index_cache",
    },
    "Item Group": {
        "after_insert": "excel_restaurant_pos.doc_event.item_group.clear_visibility_cache.clear_item_group_visibility_cache",
        "on_update": "excel_restaurant_pos.doc_event.item_group.clear_visibility_cache.clear_item_group_visibility_cache",
        "on_trash": "excel_restaurant_pos.doc_event.item_group.clear_visibility_cache.clear_item_group_visibility_cache",
    },
    "Table Order": {
        "on_update": "excel_restaurant_pos.doc_event.table_order.create_sales_invoice_from_table_order",
    },
}
