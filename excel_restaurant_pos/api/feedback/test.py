import frappe


@frappe.whitelist()
def test():
    """
    Test function
    """
    return "Test Feedback API"
