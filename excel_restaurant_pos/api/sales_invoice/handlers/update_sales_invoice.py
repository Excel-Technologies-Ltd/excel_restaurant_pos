import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate

from excel_restaurant_pos.shared.sales_invoice import build_invoice_item_row

DOCSTATUS_SUBMITTED = 1
DOCSTATUS_CANCELLED = 2


def update_sales_invoice(invoice_name, items, docstatus=None):
    """Update a Sales Invoice, optionally submitting it.

    `docstatus` accepts only 1 (submit). Cancelling is not offered here: this
    route is guest reachable and a cancel reverses posted ledger entries, which
    is not something an order endpoint should do by passing a number.
    """
    sales_invoice = frappe.get_doc("Sales Invoice", invoice_name)

    _keep_due_date_valid(sales_invoice)

    for item_data in items:
        item_code = item_data.get("item_code", None)
        if not item_code:
            frappe.throw("Item code is required", frappe.ValidationError)

        if not frappe.db.exists("Item", item_code):
            frappe.throw(f"Item {item_code} not found", frappe.ValidationError)

        sales_invoice.append("items", build_invoice_item_row(item_data))

    sales_invoice.save(ignore_permissions=True)

    _apply_docstatus(sales_invoice, docstatus)

    return sales_invoice


def _keep_due_date_valid(sales_invoice):
    """Stop a stale draft failing ERPNext's own due date rule.

    With `set_posting_time` unchecked -- which is every invoice from this API --
    ERPNext moves `posting_date` to today on each save, while `due_date` keeps
    whatever it was given when the order was taken. A draft left overnight
    therefore ends up with a due date before its posting date, and submitting it
    dies on "Due Date cannot be before Posting / Supplier Invoice Date".

    Only ever pushes the due date forward to the posting date, and only when it
    would otherwise be invalid, so an order with a real future due date keeps it.

    The payment schedule has to move with it. ERPNext's set_due_date() rebuilds
    `due_date` from the schedule rows on every validate, so fixing the field
    alone is undone before the check that reads it.
    """
    posting_date = getdate(sales_invoice.posting_date or nowdate())
    if cint(sales_invoice.get("set_posting_time")) == 0:
        # This is the date ERPNext is about to stamp on it during validate.
        posting_date = getdate(nowdate())

    for row in sales_invoice.get("payment_schedule") or []:
        if row.due_date and getdate(row.due_date) < posting_date:
            row.due_date = posting_date

    if not sales_invoice.due_date or getdate(sales_invoice.due_date) < posting_date:
        sales_invoice.due_date = posting_date


def _apply_docstatus(sales_invoice, docstatus):
    """Submit the invoice when the caller asked for it.

    Submitting is done after the save so the items in this same request are part
    of what gets submitted, and through submit() rather than by assigning
    docstatus, so the on_submit hooks actually run -- those are what post the
    ledger entries, redeem gift cards and queue the payment entry.
    """
    if docstatus in (None, ""):
        return

    requested = cint(docstatus)
    if requested == 0:
        return

    if requested != DOCSTATUS_SUBMITTED:
        frappe.throw(
            _("docstatus {0} is not supported here. Only 1 (submit) is.").format(docstatus),
            frappe.ValidationError,
        )

    # Already submitted: the caller may simply be retrying, and saying so is
    # more useful than failing a request that asked for a state it is in.
    if cint(sales_invoice.docstatus) == DOCSTATUS_SUBMITTED:
        return

    if cint(sales_invoice.docstatus) == DOCSTATUS_CANCELLED:
        frappe.throw(
            _("Order {0} was cancelled and cannot be submitted.").format(sales_invoice.name),
            frappe.ValidationError,
        )

    sales_invoice.flags.ignore_permissions = True
    sales_invoice.submit()
