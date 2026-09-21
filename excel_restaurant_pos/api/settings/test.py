import frappe


@frappe.whitelist()
def test():
    return "From Settings API"
