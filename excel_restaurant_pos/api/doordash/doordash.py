import frappe
import json
from excel_restaurant_pos.shared.customer_access import is_staff, require_login

@frappe.whitelist(allow_guest=True)
def create_order():
    # Get raw request body
    # No storefront calls this, and it creates orders: staff only.
    if not is_staff(require_login()):
        frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

    raw_body = frappe.request.get_data(as_text=True)
    print("\nRaw Body:\n", raw_body, "\n")

    # If JSON, parse it
    try:
        data = json.loads(raw_body)
        print("\nParsed JSON:\n", data, "\n")
    except Exception as e:
        print("JSON parse error:", e)

    return {"status": "received"}
