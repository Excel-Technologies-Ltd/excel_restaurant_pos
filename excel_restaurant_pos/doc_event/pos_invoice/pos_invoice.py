import frappe


@frappe.whitelist()
def create_pos_invoice(data, method=None):
    frappe.msgprint("create_pos_invoice")
    if data.get("status") != "Completed":
        return
    try:
        # Parse the incoming data
        if isinstance(data, str):
            data = frappe.parse_json(data)  # Ensure data is a dictionary
        get_restaurant_settings = frappe.get_doc("Restaurant Settings")
        tax_template_name = get_restaurant_settings.taxes_and_charges_template
        tax_template = frappe.get_doc(
            "Sales Taxes and Charges Template", tax_template_name
        )

        tax_rate = tax_template.taxes[0].get("rate", 0)
        # check type of tax_rate
        if not isinstance(tax_rate, int):
            tax_rate = int(tax_rate)
        charge_type = tax_template.taxes[0].get("charge_type")
        account_head = tax_template.taxes[0].get("account_head")

        # Create a new POS Invoice using frappe.get_doc
        invoice_doc = frappe.get_doc(
            {
                "doctype": "POS Invoice",
                "customer": data.get("customer"),
                "docstatus": 1,
                "customer_name": data.get("customer_name"),
                "company": data.get("company"),
                "posting_date": frappe.utils.today(),
                "discount_amount": int(data.get("discount", 0)),
                "apply_discount_on": "Net Total",
                "set_posting_time": 1,  # Allow posting at a specific time
                "is_pos": 1,  # Flag for POS
                "update_stock": 1,
                "pos_profile": frappe.db.get_value(
                    "POS Profile", {"company": data.get("company")}, "name"
                ),  # Assuming one profile per company
                "items": [],
                "taxes": [],
                "payments": [],
            }
        )

        # Add items to the invoice
        for item in data.get("item_list", []):
            invoice_doc.append(
                "items",
                {
                    "item_code": item.get("item"),
                    "qty": (item.get("qty", 0)),
                    "rate": (item.get("rate", 0)),
                    "amount": (item.get("amount", 0)),
                    # "discount_percentage": flt(data.get("discount")),
                },
            )

        # Add taxes to the invoice
        # tax_rate = flt(data.get("tax"))
        if tax_rate > 0:
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

        # Add payment to the invoice
        invoice_doc.append(
            "payments",
            {"mode_of_payment": "Cash", "amount": int(data.get("total_amount"))},
        )

        # Insert the document into the database
        invoice_doc.insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "POS Invoice Creation Error")
        print(e)
        frappe.msgprint(frappe.as_json(e))
        return {
            "status": "error",
            "message": str(e),
        }
