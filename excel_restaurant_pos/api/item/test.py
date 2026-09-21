import frappe


@frappe.whitelist()
def test():
    return "From Item API"
