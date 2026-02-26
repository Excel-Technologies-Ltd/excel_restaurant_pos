import frappe


@frappe.whitelist(allow_guest=False, methods=["PUT"])
def update_customer():
    """Update a customer."""

    # get customer code
    customer_code = frappe.form_dict.get("customer_code")
    if not customer_code:
        frappe.throw("Customer code is required")

    # get customer
    customer = frappe.get_doc("Customer", customer_code)
    if not customer:
        frappe.throw("Customer not found")

    # update customer info
    updated_info: dict = {}
    allow_fields = ["customer_name", "customer_type", "territory", "gender", "disabled"]

    # prepare updated info
    for field in allow_fields:
        if frappe.form_dict.get(field):
            updated_info[field] = frappe.form_dict.get(field)

    # update customer
    customer.update(updated_info)
    customer.save(ignore_permissions=True)

    # update credit limit
    credit_limits = frappe.form_dict.get("credit_limits", [])
    for credit_limit in credit_limits:
        credit_limit_doc = frappe.get_doc(
            "Customer Credit Limit", credit_limit.get("name")
        )
        credit_limit_doc.update(credit_limit)
        credit_limit_doc.save(ignore_permissions=True)
        frappe.db.commit()

    # update addresses
    addresses = frappe.form_dict.get("addresses", [])
    for address in addresses:
        address_doc = frappe.get_doc("Address", address.get("name"))
        address_doc.update(address)
        address_doc.save(ignore_permissions=True)
        frappe.db.commit()

    # update emails
    emails = frappe.form_dict.get("emails", [])
    for email in emails:
        email_doc = frappe.get_doc("Contact Email", email.get("name"))
        email_doc.update(email)
        email_doc.save(ignore_permissions=True)
        frappe.db.commit()

    # update phones
    phones = frappe.form_dict.get("phones", [])
    for phone in phones:
        phone_doc = frappe.get_doc("Contact Phone", phone.get("name"))
        phone_doc.update(phone)
        phone_doc.save(ignore_permissions=True)
        frappe.db.commit()

    # return customer
    return customer.as_dict()
