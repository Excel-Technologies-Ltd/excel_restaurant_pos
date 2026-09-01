"""Employee check in / check out endpoints."""

import frappe

from excel_restaurant_pos.api.timeclock.helpers import get_pin, get_request_data
from excel_restaurant_pos.shared.timeclock.services import authenticate_employee, check_in, check_out


@frappe.whitelist(methods=["POST"])
def timeclock_check_in():
	"""
	Record the first check in for the current business date.

	Request
	-------
	pin (required): 6-digit employee PIN
	"""
	data = get_request_data()
	employee = authenticate_employee(get_pin(data))
	return check_in(employee)


@frappe.whitelist(methods=["POST"])
def timeclock_check_out():
	"""
	Record the last check out for the current business date.

	Repeated calls before the 04:00 AM cutoff replace the stored check out time.

	Request
	-------
	pin (required): 6-digit employee PIN
	"""
	data = get_request_data()
	employee = authenticate_employee(get_pin(data))
	return check_out(employee)
