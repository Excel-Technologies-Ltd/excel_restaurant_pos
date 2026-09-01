// Copyright (c) 2026, Sohanur Rahman and contributors
// For license information, please see license.txt

frappe.ui.form.on('ArcPOS Employee', {
	refresh: function (frm) {
		frm.set_df_property('new_pin', 'description', frm.doc.pin
			? __('A PIN is set. Enter a new 6-digit PIN to replace it.')
			: __('Enter a 6-digit PIN. It is hashed on save and never stored in plain text.'));
	}
});
