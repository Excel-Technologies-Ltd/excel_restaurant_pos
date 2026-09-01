"""PIN authentication for the POS Employee Timeclock numpad."""

import frappe

from excel_restaurant_pos.api.timeclock.helpers import get_pin, get_request_data
from excel_restaurant_pos.shared.timeclock.services import authenticate_employee, get_timeclock_state


@frappe.whitelist(methods=["POST"])
def authenticate_timeclock_pin():
	"""
	Validate an employee PIN and return the action the numpad should offer.

	Request
	-------
	pin (required): 6-digit employee PIN

	Response
	--------
	employee, employee_name, role, is_manager, business_date,
	action ("check_in" | "check_out" | "blocked"), can_check_in, can_check_out,
	message, open_record, record
	"""
	data = get_request_data()
	employee = authenticate_employee(get_pin(data))
	return get_timeclock_state(employee)
