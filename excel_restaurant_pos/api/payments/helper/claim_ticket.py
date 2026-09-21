"""One Payment Entry per paid Moneris ticket.

A Moneris receipt does not go stale: ask about a ticket that was paid last week
and the gateway still answers success/approved, every time. So "the gateway says
this ticket is paid" is true of every ticket ever paid, and on its own it let one
real payment be turned into as many Payment Entries as someone cared to request
-- the Payment Ticket was looked up and then left exactly as it was.

The ticket is now claimed once, before any Payment Entry exists. The claim is a
locking read (SELECT ... FOR UPDATE) and a write in the same transaction, so a
second request for the same ticket blocks on the row lock until the first
commits, then reads the claim and backs off. Both paths that settle tickets --
api.payments.receipt_payment and the stale website order sweep in
utils/scheduled_tasks.py -- go through here, so they cannot both pay for the
same ticket either.

Anything that fails after the claim rolls the transaction back and takes the
claim with it, so a failure never burns a ticket that was not actually used.
"""

import frappe
from frappe.utils import now_datetime

TICKET_DOCTYPE = "Payment Ticket"
REDEEMED_FIELD = "redeemed_at"


def claims_supported():
    """Whether the redeemed_at column exists yet.

    It ships in the DocType, so a site between deploying the code and running
    migrate has no column. Refusing there would fail a payment the customer has
    already been charged for, which is worse than the replay window -- so it is
    logged loudly instead and the claim is skipped.
    """
    if frappe.get_meta(TICKET_DOCTYPE).has_field(REDEEMED_FIELD):
        return True

    frappe.log_error(
        title="Payment ticket claims unavailable",
        message="Payment Ticket has no redeemed_at column -- run bench migrate. "
        "Until then a paid ticket can be settled more than once.",
    )
    return False


def get_ticket(ticket):
    """The Payment Ticket row for a gateway ticket string, or None."""
    fields = ["name", "invoice_no"]
    if claims_supported():
        fields += [REDEEMED_FIELD, "redeemed_via"]

    return frappe.db.get_value(TICKET_DOCTYPE, {"ticket": ticket}, fields, as_dict=True)


def claim_ticket(ticket_name, via):
    """Mark the ticket redeemed. True if this caller is the one that did it.

    False means another request already settled it -- the caller must not
    create a Payment Entry.
    """
    if not claims_supported():
        return True

    # A locking read, not a snapshot read: a concurrent claim waits here until
    # this transaction ends, and then sees the value written below.
    already = frappe.db.get_value(TICKET_DOCTYPE, ticket_name, REDEEMED_FIELD, for_update=True)
    if already:
        return False

    frappe.db.set_value(
        TICKET_DOCTYPE,
        ticket_name,
        {REDEEMED_FIELD: now_datetime(), "redeemed_via": via},
        update_modified=False,
    )
    return True
