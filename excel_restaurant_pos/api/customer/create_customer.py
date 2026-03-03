"""Customer creation API endpoints."""

import frappe
from excel_restaurant_pos.api.address import (
    add_address_with_link,
    add_contact_with_link,
)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_customer():
    """Create a new customer with default values."""

    customer_info: dict = {}

    # required fields
    required_fields = ["customer_name", "customer_type", "territory"]
    for field in required_fields:
        if not frappe.form_dict.get(field):
            frappe.throw(f"{field} is required", frappe.MandatoryError)
        customer_info[field] = frappe.form_dict.get(field)

    # optional fields
    optional_fields = ["payment_terms", "is_frozen", "disabled", "gender"]
    for field in optional_fields:
        if frappe.form_dict.get(field):
            customer_info[field] = frappe.form_dict.get(field)

    # create customer
    customer = frappe.get_doc({"doctype": "Customer", **customer_info})

    # add credit limits
    credit_limit_fields = ["company", "credit_limit"]
    credit_limits = frappe.form_dict.get("credit_limits", [])
    for credit_limit in credit_limits:
        for field in credit_limit_fields:
            if not credit_limit.get(field):
                frappe.throw(f"{field} is required", frappe.MandatoryError)
            customer.append("credit_limits", {field: credit_limit.get(field)})

    # insert customer
    customer.insert(ignore_permissions=True)
    frappe.db.commit()

    # validate addresses
    addresses = frappe.form_dict.get("addresses", [])
    for address in addresses:
        add_address_with_link(address, "Customer", customer.name)

    # add customer contacts
    # create contact
    contact_info: dict = {"first_name": customer.customer_name}

    # get emails
    emails = frappe.form_dict.get("emails", [])
    email_ids = [email for email in emails]
    contact_info["email_ids"] = email_ids

    # get phones
    phones = frappe.form_dict.get("phones", [])
    phone_nos = [phone for phone in phones]
    contact_info["phone_nos"] = phone_nos

    # create contact
    contact = add_contact_with_link(contact_info, "Customer", customer.name)

    # format response
    response: dict = {
        **customer.as_dict(),
        "addresses": addresses,
        "contact": contact,
    }
    return response
