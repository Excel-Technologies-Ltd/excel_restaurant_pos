import frappe


@frappe.whitelist()
def test():
    return "From Menu API"
