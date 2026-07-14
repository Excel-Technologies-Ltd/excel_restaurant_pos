"""Create ArcPOS Client Contact records from customers, invoices and coupons."""

import frappe

DOCTYPE = "ArcPOS Client Contact"


def _clean(value) -> str:
    return (value or "").strip()


def email_already_registered(email: str, exclude: str | None = None) -> bool:
    """Check whether a client contact already holds this email."""
    if not email:
        return False

    filters = {"email": email}
    if exclude:
        filters["name"] = ["!=", exclude]

    return bool(frappe.db.exists(DOCTYPE, filters))


def create_client_contact(client_name=None, email=None, phone=None, customer=None):
    """Create a client contact, skipping duplicates when an email is available.

    Per spec: an email is the dedup key. Without an email there is nothing to
    dedup on, so the record is created unconditionally.
    """
    email = _clean(email)
    if email_already_registered(email):
        return None

    doc = frappe.get_doc(
        {
            "doctype": DOCTYPE,
            "client_name": _clean(client_name) or None,
            "email": email or None,
            "phone": _clean(phone) or None,
            "customer": customer or None,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def get_customer_contact_details(customer: str) -> tuple[str, str]:
    """Return (email, phone) from the Contact linked to this customer.

    Customer.email_id / mobile_no are fetch_from fields off customer_primary_contact
    and are empty in practice, so the linked Contact is the real source.
    """
    contact_names = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "link_doctype": "Customer",
            "link_name": customer,
        },
        pluck="parent",
    )

    for contact_name in contact_names:
        contact = frappe.db.get_value(
            "Contact", contact_name, ["email_id", "mobile_no", "phone"], as_dict=True
        )
        if not contact:
            continue

        email = _clean(contact.email_id)
        phone = _clean(contact.mobile_no) or _clean(contact.phone)
        if email or phone:
            return email, phone

    return "", ""


def sync_customer_client_contact(customer: str):
    """Create or complete the client contact belonging to a customer.

    Called both when the customer is created (usually before any Contact exists,
    so only the name is known) and when its Contact lands with the email/phone.
    """
    customer_name = frappe.db.get_value("Customer", customer, "customer_name")
    if not customer_name:
        return None

    email, phone = get_customer_contact_details(customer)
    existing = frappe.db.get_value(DOCTYPE, {"customer": customer}, "name")

    if not existing:
        return create_client_contact(
            client_name=customer_name, email=email, phone=phone, customer=customer
        )

    # Record exists: fill in whatever was not known at customer creation time.
    current = frappe.db.get_value(
        DOCTYPE, existing, ["client_name", "email", "phone"], as_dict=True
    )
    updates = {}
    if email and not _clean(current.email) and not email_already_registered(email, exclude=existing):
        updates["email"] = email
    if phone and not _clean(current.phone):
        updates["phone"] = phone
    if customer_name and not _clean(current.client_name):
        updates["client_name"] = customer_name

    if updates:
        frappe.db.set_value(DOCTYPE, existing, updates)

    return existing


def create_client_contact_from_customer(doc, method=None):
    """Customer after_insert: register the new customer as a client contact."""
    try:
        sync_customer_client_contact(doc.name)
    except Exception:
        frappe.log_error(
            title="Client Contact From Customer Failed",
            message=f"Customer: {doc.name}\n{frappe.get_traceback()}",
        )


def sync_client_contact_from_contact(doc, method=None):
    """Contact on_update: push the contact's email/phone onto its customers.

    on_update covers insert too, so a Contact created after its Customer (which
    is what create_customer does) still completes the record.
    """
    customers = [
        link.link_name
        for link in (doc.get("links") or [])
        if link.link_doctype == "Customer" and link.link_name
    ]

    for customer in customers:
        try:
            sync_customer_client_contact(customer)
        except Exception:
            frappe.log_error(
                title="Client Contact From Contact Failed",
                message=f"Contact: {doc.name} Customer: {customer}\n{frappe.get_traceback()}",
            )


def create_client_contact_from_invoice(doc, method=None):
    """Sales Invoice after_insert: register the ordering customer's details."""
    email = _clean(doc.get("custom_email_address"))
    if not email:
        return

    try:
        create_client_contact(
            client_name=doc.get("custom_customer_full_name"),
            email=email,
            phone=doc.get("custom_mobile_no"),
        )
    except Exception:
        frappe.log_error(
            title="Client Contact From Invoice Failed",
            message=f"Sales Invoice: {doc.name}\n{frappe.get_traceback()}",
        )


def create_client_contact_from_coupon(doc, method=None):
    """Coupon Code after_insert: register standalone coupons by email only.

    Coupons generated for an invoice are skipped -- the invoice already registers
    the contact. The invoice link is deferred to on_submit for auto-generated
    coupons, so custom_generated_on_order is still empty here; create_coupon_doc
    sets the generated_for_invoice flag to cover that window.
    """
    if doc.get("custom_generated_on_order") or doc.flags.get("generated_for_invoice"):
        return

    email = _clean(doc.get("custom_linked_email"))
    if not email:
        return

    try:
        create_client_contact(email=email)
    except Exception:
        frappe.log_error(
            title="Client Contact From Coupon Failed",
            message=f"Coupon Code: {doc.name}\n{frappe.get_traceback()}",
        )
