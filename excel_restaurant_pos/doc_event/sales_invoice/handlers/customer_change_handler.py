"""Notification context for order accepted emails."""

# pylint: disable=invalid-name
import frappe
from excel_restaurant_pos.excel_restaurant_pos.notification.utils import (
    get_customer_primary_email,
)


def customer_change_handler(doc):
    """Set the primary email recipient for order accepted (not from table) notifications.

    Args:
        context: Dictionary containing the document context
    """
    default_customer = frappe.db.get_single_value("ArcPOS Settings", "customer")
    d_web_customer = frappe.db.get_single_value(
        "ArcPOS Settings", "default_customer_website"
    )

    # define the primary email
    primary_email = None

    # if bill on default customer
    if doc.customer in [default_customer, d_web_customer]:
        primary_email = doc.custom_email_address
    else:
        primary_email = get_customer_primary_email(doc.customer)

    # if no primary email is found, set the custom email send to to empty string
    if not primary_email:
        msg = f"No primary email found for Sales Invoice {doc.name if doc.name else 'NEW'} (Customer: {doc.customer})"
        frappe.log_error("No Email Address", msg)
        primary_email = ""

    # Set the email - use db.set_value if document exists, otherwise set on doc
    # Use db.set_value to avoid "Document has been modified" error during save flow
    if doc.name:
        # Document exists in DB - use db.set_value to avoid version conflict
        try:
            frappe.db.set_value(
                "Sales Invoice",
                doc.name,
                "custom_email_send_to",
                primary_email,
            )
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(
                "Customer Change Handler Error",
                f"Error setting custom_email_send_to for {doc.name}: {str(e)}",
            )
    else:
        # Document not saved yet - set on doc object (will be saved with the document)
        doc.custom_email_send_to = primary_email
