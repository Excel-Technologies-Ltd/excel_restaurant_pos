import frappe
from frappe import _

from .helper.check_receipt import check_receipt
from .helper.get_payment_config import get_payment_config
from excel_restaurant_pos.shared.customer_access import access_level, require_login
from .helper.claim_ticket import claim_ticket, get_ticket
from .helper.settlement import MISMATCH, settlement_payments, verify_charged_amount
from excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry import (
    create_payment_entry,
)


@frappe.whitelist()
def receipt_payment():
    """
    Receipt a payment ticket.
    """

    # validate ticket
    require_login()
    ticket = frappe.form_dict.get("ticket")
    invoice_name = frappe.form_dict.get("order_no")
    if not ticket or not invoice_name:
        frappe.throw("Ticket and order number are required")

    # get ticket details
    ticket_row = get_ticket(ticket)
    if not ticket_row or not ticket_row.invoice_no:
        frappe.throw("Ticket not found")
    invoice_no = ticket_row.invoice_no
    # Only the order's owner (or staff) may settle it.
    access_level(invoice_no)

    # Already settled. Answered as done rather than processed again: a real
    # customer retrying after a lost response should not see a payment failure
    # for a payment that went through, and a replay gets nothing -- no second
    # Payment Entry is made. Checked before the gateway call because Moneris
    # would answer "approved" for this ticket forever.
    if ticket_row.get("redeemed_at"):
        return _already_processed(ticket_row, invoice_name)

    # check receipt status info
    receipt_status = check_receipt(ticket)

    # define required values for validation
    receipt_result = receipt_status.get("receipt", {}).get("result", "")
    success_result = receipt_status.get("success", "false")

    # Check the payment succeeded and the receipt was approved.
    #
    # There was an `environment == "development"` escape hatch here that skipped
    # this entirely. It is gone: site_config carries two keys called
    # `environment` -- this one, and the Moneris store selector under `payment`
    # -- so a plausible tidy-up, or one afternoon of debugging, silently turned
    # payment verification off for everyone with no error and no log line.
    #
    # Nothing is lost by removing it. `payment.environment` already points a dev
    # site at the Moneris QA store, which issues real tickets and real approval
    # codes, so development tests the same path production runs.
    if success_result != "true" or receipt_result != "a":
        # What Moneris said, without card data -- the refusal alone does not
        # tell a declined card from a QA ticket checked against production,
        # or an amount decline from a failed CVV/address/3-D Secure check.
        cc = (receipt_status.get("receipt") or {}).get("cc") or {}
        frappe.log_error(
            title="Payment not approved by Moneris",
            message=(
                f"invoice={invoice_no} order_no={invoice_name} success={success_result!r} "
                f"result={receipt_result!r} error={receipt_status.get('error')!r} "
                f"environment={get_payment_config().get('environment')!r}\n"
                f"amount={cc.get('amount')!r} response_code={cc.get('response_code')!r} "
                f"iso_response_code={cc.get('iso_response_code')!r}\n"
                f"fraud={cc.get('fraud')!r}"
            ),
        )
        frappe.throw("Invalid or expired payment ticket", frappe.ValidationError)

    # # validate order number
    order_number = receipt_status.get("request", {}).get("order_no")
    if order_number != invoice_name:
        frappe.throw("Order number mismatch", frappe.ValidationError)

    # get invoice
    invoice = frappe.get_doc("Sales Invoice", invoice_no)
    if not invoice:
        frappe.throw("Invoice not found")

    # The Payment Entry is booked at the invoice's own grand_total. It used to
    # take `payments[].amount` from the request, so a $5 payment could be booked
    # as $500 -- and since a draft can still be edited after its ticket is
    # issued, a cart preloaded at $1 could be grown before paying that $1 ticket.
    # Checked against what Moneris charged before anything is claimed, so a
    # mismatch leaves the ticket unspent for staff to review.
    if verify_charged_amount(receipt_status, invoice) == MISMATCH:
        frappe.throw(
            _("The amount paid does not match this order. Please contact the restaurant."),
            frappe.ValidationError,
        )

    # The request's `payments` is no longer trusted for anything but a fallback
    # mode of payment, used only when no website mode is configured.
    payments = settlement_payments(invoice, fallback_mode=_requested_mode())

    # Claim the ticket before any Payment Entry exists. A concurrent request for
    # the same ticket waits on the row lock here and then backs off; if anything
    # below fails, the rollback releases the claim with everything else.
    if not claim_ticket(ticket_row.name, via="receipt_payment"):
        return _already_processed(ticket_row, invoice_name)

    # submit sales invoice with payment data
    invoice.docstatus = 1
    invoice.save(ignore_permissions=True)

    # enqueue payment entry creation
    args = {"sales_invoice": invoice.name, "payments": payments}
    create_payment_entry(**args)
    # frappe.enqueue(create_payment_entry, queue="short", **args)

    # return True
    return {"success": True}


def _already_processed(ticket_row, invoice_name):
    """The response for a ticket that has already paid for its order."""
    if invoice_name != ticket_row.invoice_no:
        frappe.throw("Order number mismatch", frappe.ValidationError)

    return {"success": True, "already_processed": True}


def _requested_mode():
    """The mode of payment the client asked for, if it sent one."""
    payments = frappe.form_dict.get("payments")
    if isinstance(payments, str):
        try:
            payments = frappe.parse_json(payments)
        except Exception:
            return None

    if isinstance(payments, list) and payments and isinstance(payments[0], dict):
        return payments[0].get("mode_of_payment")

    return None
