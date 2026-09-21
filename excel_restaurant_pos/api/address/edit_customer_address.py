import frappe


@frappe.whitelist()
def edit_customer_address():

    # validate name
    name = frappe.form_dict.get("name")
    if not name:
        frappe.throw("Name for the address is required to edit an address")

    # validate address
    if not frappe.db.exists("Address", name):
        frappe.throw(f"Address {name} not found. Please check the name and try again.")

    # get address
    address = frappe.get_doc("Address", name)

    # update address
    allowed_fields = [
        "address_type",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "country",
        "pincode",
        "email_id",
        "phone",
    ]
    for field in allowed_fields:
        if frappe.form_dict.get(field):
            setattr(address, field, frappe.form_dict.get(field))

    # save address
    address.save(ignore_permissions=True)

    # return address
    return address.as_dict()
