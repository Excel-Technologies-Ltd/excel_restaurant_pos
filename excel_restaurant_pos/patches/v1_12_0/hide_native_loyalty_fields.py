"""Hide ERPNext's own loyalty fields: ArcPOS loyalty replaces them, and two would confuse staff.

Also reports any Customer still enrolled in an ERPNext Loyalty Program; the
Sales Invoice validate hook keeps those from earning, but they should be
cleared.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

HIDDEN = {
	"Sales Invoice": ("loyalty_points_redemption", "loyalty_program", "redeem_loyalty_points"),
	"Customer": ("loyalty_points_tab", "loyalty_program", "loyalty_program_tier"),
}


def execute():
	for doctype, fieldnames in HIDDEN.items():
		meta = frappe.get_meta(doctype)
		for fieldname in fieldnames:
			if meta.has_field(fieldname):
				make_property_setter(doctype, fieldname, "hidden", 1, "Check", validate_fields_for_doctype=False)

	enrolled = frappe.db.count("Customer", {"loyalty_program": ["is", "set"]})
	if enrolled:
		frappe.log_error(
			title="Customers still in an ERPNext Loyalty Program",
			message=(
				f"{enrolled} Customer(s) have Customer.loyalty_program set. ArcPOS loyalty replaces the native "
				"programme and invoices no longer earn through it; clear the field to avoid confusion."
			),
		)
