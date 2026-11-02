# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ArcPOSWalletDeviceRegistration(Document):
	pass


def on_doctype_update():
	# Not frappe.db.add_unique: in v14 it looks the constraint up in
	# information_schema without naming the database, so on a bench whose sites
	# share one MariaDB server every site after the first finds the first
	# site's constraint and never creates its own.
	constraint = "unique_device_library_id_pass"
	exists = frappe.db.sql(
		"""
		SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
		WHERE table_schema = DATABASE() AND table_name = %s
			AND constraint_type = 'UNIQUE' AND constraint_name = %s
		""",
		("tabArcPOS Wallet Device Registration", constraint),
	)
	if not exists:
		frappe.db.commit()
		frappe.db.sql_ddl(
			f"ALTER TABLE `tabArcPOS Wallet Device Registration` ADD UNIQUE `{constraint}` (device_library_id, `pass`)"
		)
