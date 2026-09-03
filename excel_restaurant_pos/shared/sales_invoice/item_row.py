"""Build Sales Invoice Item rows from POS payloads.

The POS sends cart lines to `api.sales_invoices.add`. Rather than repeating a
hard-coded list of custom fieldnames in every endpoint, the allowed custom
fields are read from the DocType meta, so a custom field added later (the gift
card ones, for example) reaches the invoice without another code change.
"""

import frappe
from frappe.model import no_value_fields
from frappe.utils import flt


# Core fields the POS may set directly. Everything else it sends is restricted
# to custom fields, so a guest request can never reach the accounting fields
# (income_account, cost_center, price_list_rate, ...).
CORE_ITEM_FIELDS = ("item_code", "qty", "rate", "warehouse", "description")

# Attachments are excluded on top of the layout/child-table fieldtypes: a file
# path from an untrusted payload has no business being written to an invoice.
SKIPPED_FIELDTYPES = set(no_value_fields) | {"Attach", "Attach Image"}

# Only the `custom_` prefix is accepted, not every custom field. Sales Invoice
# Item also carries the `excel_*` accounting dimensions (Excel LC No, Excel
# Short Term Loan, ...), which belong to Accounts, not to the POS.
CUSTOM_FIELD_PREFIX = "custom_"


def get_allowed_custom_item_fields(doctype="Sales Invoice Item"):
    """POS-owned custom fieldnames on `doctype` that a payload may set."""
    meta = frappe.get_meta(doctype)
    return tuple(
        df.fieldname
        for df in meta.fields
        if df.fieldtype not in SKIPPED_FIELDTYPES
        and df.fieldname.startswith(CUSTOM_FIELD_PREFIX)
    )


def build_invoice_item_row(item_data):
    """Map one payload line onto a Sales Invoice Item row.

    Keys the payload does not carry are left out entirely so the field defaults
    still apply.
    """
    row = {
        "item_code": item_data.get("item_code"),
        "qty": flt(item_data.get("qty", 1)),
        "rate": flt(item_data.get("rate", 0)),
        "warehouse": item_data.get("warehouse"),
        "description": item_data.get("description"),
    }

    for fieldname in get_allowed_custom_item_fields():
        if fieldname in item_data:
            row[fieldname] = item_data.get(fieldname)

    return row
