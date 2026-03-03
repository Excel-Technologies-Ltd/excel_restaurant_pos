"""
Helper function to check receipt status from payment gateway.
"""

import requests
import frappe
from .get_payment_config import get_payment_config


def check_receipt(ticket: str) -> bool:
    """
    Check the receipt status of a payment ticket from the payment gateway.

    Args:
        ticket: The payment ticket string to check receipt status for

    Returns:
        bool: True if receipt status is "1" (paid), False otherwise

    Raises:
        frappe.ValidationError: If ticket is not provided, request fails,
            or response is invalid

    Example:
        >>> check_receipt("ticket_abc123")
        True
    """
    if not ticket:
        frappe.throw("Ticket is required", frappe.ValidationError)

    payment_config = get_payment_config()

    # Prepare payload
    payload = {
        "store_id": payment_config.get("store_id"),
        "api_token": payment_config.get("api_token"),
        "checkout_id": payment_config.get("checkout_id"),
        "ticket": ticket,
        "environment": payment_config.get("environment"),
        "action": "receipt",
    }

    # Send request to payment gateway
    try:
        response = requests.post(payment_config["ticket_url"], json=payload, timeout=30)
    except requests.exceptions.RequestException as e:
        frappe.log_error(
            "Receipt Status Error", f"Receipt status check request failed: {str(e)}"
        )
        frappe.throw("Failed to connect to payment gateway", frappe.ValidationError)

    # Check HTTP status code
    if response.status_code != 200:
        error_msg = f"Payment gateway returned status {response.status_code}"
        try:
            error_detail = response.text[:200]  # First 200 chars of error
            frappe.log_error("Receipt Status Error", f"{error_msg}: {error_detail}")
        except Exception:
            pass
        frappe.throw(
            f"Failed to check receipt status: {error_msg}", frappe.ValidationError
        )

    # Parse JSON response
    try:
        response_data = response.json()
    except ValueError as e:
        frappe.log_error(
            "Receipt Status Error",
            f"Invalid JSON response from payment gateway: {str(e)}",
        )
        frappe.throw("Invalid response from payment gateway", frappe.ValidationError)

    # Return True if receipt_status is "1", False otherwise
    return response_data.get("response", {})
