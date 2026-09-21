"""API endpoint for adding customer addresses."""

import frappe

from .handlers.add_address_with_link import add_address_with_link


@frappe.whitelist()
def add_customer_address():
    """
    Add a new customer address
    """
    # validate customer code
    customer_code = frappe.form_dict.get("customer_code")
    if not customer_code:
        return frappe.throw("Customer code is required")

    # get customer
    customer = frappe.get_doc("Customer", customer_code)
    if not customer:
        return frappe.throw("Customer not found")

    # append address to customer
    address_info: dict = {}

    # required fields
    required_fields = ["address_type", "address_line1", "city", "country"]
    for field in required_fields:
        if not frappe.form_dict.get(field):
            frappe.throw(f"{field} is required", frappe.MandatoryError)
        address_info[field] = frappe.form_dict.get(field)

    # optional fields
    optional_fields = ["address_line2", "state", "pincode"]
    for field in optional_fields:
        if frappe.form_dict.get(field):
            address_info[field] = frappe.form_dict.get(field)

    # create address
    new_address = add_address_with_link(address_info, "Customer", customer.name)

    # return address
    return {
        "message": "Address added successfully",
        "address": new_address,
    }
