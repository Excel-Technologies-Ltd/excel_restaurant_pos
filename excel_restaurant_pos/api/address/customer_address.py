import frappe


@frappe.whitelist(allow_guest=False)
def get_customer_address() -> dict:
    """
    Get customer address - Optimized version with fewer DB calls
    """
    # validate customer code
    customer_code = frappe.form_dict.pop("customer_code", None)
    if not customer_code:
        frappe.throw("Customer code is required")

    # get the customer details
    customer_dict = frappe.get_doc("Customer", customer_code).as_dict()
    if not customer_dict:
        frappe.throw(
            f"Customer {customer_code} does not exist", frappe.DoesNotExistError
        )

    # get the dynamic link
    all_links = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Customer",
            "link_name": customer_code,
        },
        fields=["parent", "parenttype"],
    )

    # Separate addresses and contacts
    address_names = [link.parent for link in all_links if link.parenttype == "Address"]
    contact_names = [link.parent for link in all_links if link.parenttype == "Contact"]

    # remove cmd from filter
    frappe.form_dict.pop("cmd", None)

    # Get addresses if they exist
    if address_names:
        # Prepare filters for addresses
        filters = frappe.form_dict.get("filters")
        if filters:
            filters = frappe.parse_json(filters)
            filters.append(["name", "in", address_names])
        else:
            filters = [["name", "in", address_names]]

        frappe.form_dict["filters"] = filters
        addresses_doclist = frappe.get_all("Address", **frappe.form_dict)
    else:
        addresses_doclist = []

    # get the phones and emails from the contacts
    if contact_names:
        phone_list = frappe.get_all(
            "Contact Phone",
            filters=[["parent", "in", contact_names]],
            fields=["name", "phone", "is_primary_phone", "is_primary_mobile_no"],
        )
        email_list = frappe.get_all(
            "Contact Email",
            filters=[["parent", "in", contact_names]],
            fields=["name", "email_id", "is_primary"],
        )
    else:
        phone_list = []
        email_list = []

    # Return the result
    customer_dict["addresses"] = addresses_doclist
    customer_dict["phones"] = phone_list
    customer_dict["emails"] = email_list
    return customer_dict
