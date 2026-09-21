import frappe


@frappe.whitelist()
def test():
    return "Tips API is working"
