import frappe


def add_contact_with_link(contact_info: dict, link_doctype: str, link_name: str):
    """Add a contact to a link."""

    # get existing contact
    contact_links = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "link_doctype": link_doctype,
            "link_name": link_name,
        },
        fields=["parent"],
        limit=1,
    )

    if contact_links:
        contact = frappe.get_doc("Contact", contact_links[0].parent)
        contact.update(contact_info)
        contact.save(ignore_permissions=True)
        frappe.db.commit()
    else:
        contact = frappe.get_doc({"doctype": "Contact", **contact_info})
        contact.append("links", {"link_doctype": link_doctype, "link_name": link_name})
        contact.insert(ignore_permissions=True)
        frappe.db.commit()

    return contact.as_dict()
