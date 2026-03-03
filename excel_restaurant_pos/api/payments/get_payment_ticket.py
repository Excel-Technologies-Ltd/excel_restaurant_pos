import requests
import frappe
from frappe.utils import now_datetime, get_datetime

from excel_restaurant_pos.shared.sales_invoice import delete_delivery_draft_invoice
from excel_restaurant_pos.utils import convert_to_flt_string, convert_to_decimal_string
from .helper.get_ticket_from_db import get_ticket_from_db
from .helper.get_payment_config import get_payment_config
from .helper.save_ticket_to_db import save_ticket_to_db


def _validate_invoice_number() -> str:
    """
    Validate and extract invoice number from form_dict.

    Returns:
        str: The invoice number

    Raises:
        frappe.ValidationError: If invoice number is not provided
    """
    invoice_number = frappe.form_dict.get("invoice_number", None)
    if not invoice_number:
        frappe.throw("Invoice number is required")
    return invoice_number


def _get_invoice(invoice_number: str):
    """
    Get and validate the sales invoice.

    Args:
        invoice_number: The invoice number to retrieve

    Returns:
        Document: The Sales Invoice document

    Raises:
        frappe.DoesNotExistError: If invoice is not found
    """
    invoice = frappe.get_doc("Sales Invoice", invoice_number)
    if not invoice:
        frappe.throw("Invoice not found", frappe.DoesNotExistError)
    return invoice


def _get_existing_ticket_if_valid(invoice_number: str) -> dict | None:
    """
    Check if a valid payment ticket exists for the invoice.

    A ticket is considered valid if it exists and was created less than 8 minutes ago.

    Args:
        invoice_number: The invoice number to check

    Returns:
        dict | None: {"ticket": ticket} if valid ticket exists, None otherwise

    Raises:
        frappe.ValidationError: If ticket exists but is expired (> 8 minutes old)
    """
    payment_ticket_data = get_ticket_from_db(invoice_number)

    if payment_ticket_data and payment_ticket_data.get("ticket"):
        ticket = payment_ticket_data.get("ticket")
        creation_time = get_datetime(payment_ticket_data.get("creation"))
        current_time = now_datetime()

        # Calculate time difference in minutes
        time_diff_minutes = (current_time - creation_time).total_seconds() / 60

        # If ticket is more than 8 minutes old, delete invoice and throw error
        if time_diff_minutes > 8:
            delete_delivery_draft_invoice(invoice_number)
            frappe.throw("Invalid order or expired session", frappe.ValidationError)

        # Ticket is valid (less than 8 minutes old), return it
        return {"ticket": ticket}

    return None


def _prepare_cart_items(invoice) -> list:
    """
    Prepare cart items from invoice items.

    Args:
        invoice: The Sales Invoice document

    Returns:
        list: Formatted list of cart items
    """
    fmt_items = []
    for item in invoice.items:
        fmt_items.append(
            {
                "url": item.get("image", "").replace("/", "\\/"),
                "description": item.item_name,
                "product_code": item.item_code,
                "unit_cost": convert_to_flt_string(item.rate),
                "quantity": convert_to_decimal_string(item.qty),
            }
        )
    return fmt_items


def _prepare_payment_payload(invoice, payment_config: dict) -> dict:
    """
    Prepare the payment ticket request payload.

    Args:
        invoice: The Sales Invoice document
        payment_config: Payment gateway configuration

    Returns:
        dict: The payment ticket payload
    """
    payload = {
        "store_id": payment_config["store_id"],
        "api_token": payment_config["api_token"],
        "checkout_id": payment_config["checkout_id"],
        "environment": payment_config["environment"],
        "language": "en",
        "action": "preload",
        "txn_total": convert_to_flt_string(invoice.grand_total),
        "order_no": invoice.name,
        "cust_id": invoice.customer,
    }

    cart = {
        "items": _prepare_cart_items(invoice),
        "subtotal": convert_to_flt_string(invoice.net_total),
        "tax": {
            "amount": convert_to_flt_string(invoice.total_taxes_and_charges),
            "description": "Taxes and Charges",
        },
    }

    payload["cart"] = cart
    return payload


def _request_payment_ticket(payload: dict, payment_config: dict) -> str:
    """
    Send request to payment gateway and parse response.

    Args:
        payload: The payment ticket request payload
        payment_config: Payment gateway configuration

    Returns:
        str: The payment ticket string

    Raises:
        frappe.ValidationError: If request fails or response is invalid
    """
    # Send the payment ticket request
    try:
        response = requests.post(payment_config["ticket_url"], json=payload, timeout=30)
    except requests.exceptions.RequestException as e:
        frappe.log_error(
            "Payment Ticket Error", f"Payment gateway request failed: {str(e)}"
        )
        frappe.throw("Failed to connect to payment gateway", frappe.ValidationError)

    if response.status_code != 200:
        error_msg = f"Payment gateway returned status {response.status_code}"
        try:
            error_detail = response.text[:200]  # First 200 chars of error
            frappe.log_error("Payment Ticket Error", f"{error_msg}: {error_detail}")
        except Exception:
            pass
        frappe.throw(
            f"Failed to get payment ticket: {error_msg}", frappe.ValidationError
        )

    # Parse response
    try:
        response_data = response.json()
    except ValueError as e:
        frappe.log_error(
            "Payment Ticket Error",
            f"Invalid JSON response from payment gateway: {str(e)}",
        )
        frappe.throw("Invalid response from payment gateway", frappe.ValidationError)

    res = response_data.get("response", {})
    print(res)
    if res.get("success", "false").lower() != "true":
        error_message = res.get("message", "Unknown error from payment gateway")
        frappe.log_error(
            "Payment Ticket Error", f"Payment gateway error: {error_message}"
        )
        frappe.throw(
            f"Failed to get payment ticket: {error_message}", frappe.ValidationError
        )

    ticket = res.get("ticket")
    if not ticket:
        frappe.throw("Payment ticket not found in response", frappe.ValidationError)

    return ticket


@frappe.whitelist(allow_guest=True)
def get_payment_ticket():
    """
    Get payment ticket for an invoice.

    Checks for existing valid ticket first. If none exists or it's expired,
    creates a new ticket from the payment gateway.

    Returns:
        dict: {"ticket": ticket_string}
    """
    # Validate and get invoice number
    invoice_number = _validate_invoice_number()

    # Get and validate invoice
    invoice = _get_invoice(invoice_number)

    # Check for existing valid ticket
    existing_ticket = _get_existing_ticket_if_valid(invoice_number)
    if existing_ticket:
        return existing_ticket

    # Get payment config
    payment_config = get_payment_config()

    # Prepare payload
    payload = _prepare_payment_payload(invoice, payment_config)
    print(payload)

    # Request new ticket from payment gateway
    ticket = _request_payment_ticket(payload, payment_config)

    # Save ticket to database
    save_ticket_to_db(invoice_number, ticket)

    return {"ticket": ticket}
