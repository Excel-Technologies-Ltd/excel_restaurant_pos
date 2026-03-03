import frappe
from frappe.utils import flt


def create_sales_invoice(doc, method=None, create_payment=True):
    """
    Create Sales Invoice with support for multiple payment methods
    """
    if doc.status != "Completed":
        return

    try:
        # Validate required fields
        if not doc.customer:
            frappe.throw("Customer is required")
        if not doc.item_list or len(doc.item_list) == 0:
            frappe.throw("At least one item is required")

        # Get restaurant settings and tax configuration
        get_restaurant_settings = frappe.get_doc("Restaurant Settings")
        tax_template_name = get_restaurant_settings.taxes_and_charges_template
        bom_settings = frappe.get_doc("Restaurant Production Config")

        if not tax_template_name:
            frappe.throw("Tax template not configured in Restaurant Settings")

        tax_template = frappe.get_doc(
            "Sales Taxes and Charges Template", tax_template_name
        )

        # Get tax details (handle empty taxes)
        tax_rate = 0
        charge_type = "On Net Total"
        account_head = ""

        if tax_template.taxes and len(tax_template.taxes) > 0:
            tax_rate = flt(tax_template.taxes[0].get("rate", 0))
            charge_type = tax_template.taxes[0].get("charge_type", "On Net Total")
            account_head = tax_template.taxes[0].get("account_head", "")

        # Create Sales Invoice
        invoice_doc = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": doc.customer,
                "docstatus": 0,
                "customer_name": doc.customer_name,
                "company": doc.company,
                "posting_date": frappe.utils.today(),
                "discount_amount": flt(doc.discount or 0),
                "apply_discount_on": "Net Total",
                "set_posting_time": 1,
                "update_stock": 1,
                "items": [],
                "taxes": [],
            }
        )

        # Add items to the invoice
        for item in doc.item_list:
            if not item.item:
                continue  # Skip items without item code

            invoice_doc.append(
                "items",
                {
                    "item_code": item.item,
                    "qty": flt(item.qty or 0),
                    "rate": flt(item.rate or 0),
                    "amount": flt(item.amount or 0),
                    "warehouse": bom_settings.target_warehouse,
                },
            )

        # Add taxes if configured
        if tax_rate > 0 and account_head:
            invoice_doc.append(
                "taxes",
                {
                    "charge_type": charge_type,
                    "account_head": account_head,
                    "rate": tax_rate,
                    "description": "Sales Tax",
                    "included_in_print_rate": 0,
                },
            )

        # Insert and submit the invoice
        invoice_doc.insert(ignore_permissions=True)
        invoice_doc.submit()

        # Create Payment Entries for multiple payment methods
        payment_methods = doc.payment_methods
        payment_entries = []

        # Debug: Log the payment methods received
        frappe.log_error(
            "Payment Debug 1",
            f"Payment count: {len(payment_methods)}, Type: {type(payment_methods)}",
        )

        # Convert Frappe document objects to dictionaries
        if payment_methods and len(payment_methods) > 0:
            # Check if first element is a Frappe document
            if hasattr(payment_methods[0], "as_dict"):
                payment_methods = [p.as_dict() for p in payment_methods]
                frappe.log_error(
                    "Payment Debug 2",
                    f"Converted {len(payment_methods)} payments",
                )

        if len(payment_methods) > 0:
            for idx, payment in enumerate(payment_methods):
                payment_amount = 0
                mode_of_payment = "Cash"
                reference_no = ""

                # Parse payment data
                if isinstance(payment, dict):
                    payment_amount = flt(payment.get("amount", 0))
                    mode_of_payment = payment.get("method", "Cash")
                    reference_no = payment.get("reference", "")
                    frappe.log_error(
                        "Payment Debug 3",
                        f"Pay {idx + 1}: {mode_of_payment} = {payment_amount}",
                    )
                else:
                    # Try to access as object attributes
                    try:
                        payment_amount = flt(getattr(payment, "amount", 0))
                        mode_of_payment = getattr(payment, "method", "Cash")
                        reference_no = getattr(payment, "reference", "")
                        frappe.log_error(
                            "Payment Debug 4",
                            f"Pay {idx + 1} obj: {mode_of_payment} = {payment_amount}",
                        )
                    except Exception as attr_error:
                        frappe.log_error(
                            "Payment Parse Error",
                            f"Parse err {idx + 1}: {str(attr_error)}",
                        )
                        continue

                # Create payment entry if amount is valid
                if payment_amount > 0:
                    pass
                    # try:
                    #     frappe.log_error(
                    #         f"Creating: {mode_of_payment} = {payment_amount}",
                    #         "Payment Debug 5",
                    #     )
                    #     payment_entry = create_payment_entry(
                    #         invoice_doc=invoice_doc,
                    #         mode_of_payment=mode_of_payment,
                    #         amount=payment_amount,
                    #         company=doc.company,
                    #         reference_no=reference_no,
                    #     )
                    #     payment_entries.append(payment_entry.name)
                    #     frappe.log_error(
                    #         f"Created: {payment_entry.name}", "Payment Debug 6"
                    #     )
                    # except Exception as pe_error:
                    #     frappe.log_error(
                    #         f"Failed {mode_of_payment}: {str(pe_error)}\n{frappe.get_traceback()}",
                    #         "Payment Entry Error",
                    #     )

                else:
                    frappe.log_error("Payment Debug 7", f"Skip {idx + 1}: zero amount")

        # Update Table Order if provided
        if doc.name:
            try:
                frappe.db.set_value(
                    "Table Order", doc.name, "sales_invoice", invoice_doc.name
                )
                frappe.db.commit()
            except Exception as update_error:
                frappe.log_error(
                    "Table Order Error",
                    f"Failed Table Order update: {str(update_error)}",
                )

        return {
            "status": "success",
            "invoice_name": invoice_doc.name,
            "payment_entries": payment_entries,
            "message": f"Sales Invoice created successfully with {len(payment_entries)} payment(s)",
        }

    except Exception as e:
        frappe.log_error("Sales Invoice Error", frappe.get_traceback())
        frappe.throw(f"Failed to create Sales Invoice: {str(e)}")
