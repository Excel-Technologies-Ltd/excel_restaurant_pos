"""Stop order emails being sent from the hardcoded notifications@excelbd.com.

The five Notification records this app ships carried that address, so every
site -- whatever Email Account it had configured -- sent its order emails from
it. The address is out of the shipped files now, but removing a field from a
record file does not clear what is already stored: Frappe only writes back the
fields the file still has. This clears the stored value, once.

Notifications created in Desk with the same address are cleared too; they were
copied from the shipped ones. Emptying both fields makes Frappe fall back to the
site's default outgoing Email Account, which is what every site should use.

Any other notification that still names its own sender is logged rather than
changed: that address was chosen on the site, and is for its admins to review.
"""

import frappe

OLD_SENDER_EMAIL = "notifications@excelbd.com"


def execute():
	names = frappe.get_all("Notification", filters={"sender_email": OLD_SENDER_EMAIL}, pluck="name")
	for name in names:
		frappe.db.set_value(
			"Notification", name, {"sender": None, "sender_email": None}, update_modified=False
		)

	remaining = frappe.get_all(
		"Notification",
		filters={"sender_email": ["is", "set"]},
		fields=["name", "sender_email"],
	)
	if names or remaining:
		frappe.logger().info(
			f"cleared the hardcoded sender from {len(names)} notification(s): {names}; "
			f"still sending from their own address: {remaining}"
		)
