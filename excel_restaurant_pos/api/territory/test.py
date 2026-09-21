import frappe


@frappe.whitelist()
def test():
    """
    Test function
    """
    return "test"
