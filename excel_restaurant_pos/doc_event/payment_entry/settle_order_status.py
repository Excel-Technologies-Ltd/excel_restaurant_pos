"""Settle order status when a Payment Entry pays off a Sales Invoice."""

import frappe

from excel_restaurant_pos.doc_event.sales_invoice.handlers.payment_change_handler import (
    payment_change_handler,
)


def settle_order_status_on_payment(doc, method=None):
    """Payment Entry on_submit: close the orders this payment settled.

    change_sales_invoice reacts to ``has_value_changed("status")``, which only
    holds when the transition happens during a document save. ERPNext instead
    flips Sales Invoice.status to Paid with db_set (set_status(update=True), via
    update_outstanding_amounts), which fires no doc events and writes no version
    row -- so a payment taken through a Payment Entry was invisible to it and the
    order stayed open. This is the event that actually happens, so trigger here.

    PaymentEntry.on_submit calls update_outstanding_amounts() before doc event
    hooks run, so the invoice status is already settled by the time we read it.
    """
    for ref in doc.get("references") or []:
        if ref.reference_doctype != "Sales Invoice" or not ref.reference_name:
            continue

        # A partial payment leaves the invoice unpaid; the handler would only bail.
        if frappe.db.get_value("Sales Invoice", ref.reference_name, "status") != "Paid":
            continue

        # enqueue_after_commit: the handler re-reads the invoice on another
        # connection and would otherwise race this transaction's commit.
        frappe.enqueue(
            payment_change_handler,
            queue="default",
            enqueue_after_commit=True,
            invoice_name=ref.reference_name,
        )
