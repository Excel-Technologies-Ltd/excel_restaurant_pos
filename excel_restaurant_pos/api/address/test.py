import frappe


@frappe.whitelist()
def test():
    """
    Test function
    """
    return "Test Address API"
