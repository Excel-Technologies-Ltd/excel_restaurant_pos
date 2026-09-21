import frappe


@frappe.whitelist()
def test():
    return "From Item Group API"
