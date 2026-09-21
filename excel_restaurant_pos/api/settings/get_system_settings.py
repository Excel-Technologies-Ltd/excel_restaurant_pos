import frappe


@frappe.whitelist()
def get_system_settings():
    """
    Get system settings
    """
    settings = frappe.get_single("ArcPOS System Settings")
    return settings.as_dict()
