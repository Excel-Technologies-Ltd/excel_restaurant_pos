"""Manager override endpoints for the Employee Timeclock (Manager role PIN required)."""

import frappe
from frappe.utils import cint

from excel_restaurant_pos.api.timeclock.helpers import (
	get_business_date_param,
	get_pin,
	get_request_data,
)
from excel_restaurant_pos.shared.timeclock.services import (
	authenticate_manager,
	create_manual_entry,
	get_employee_options,
	get_record_for_manager,
	serialize_employee,
	update_record,
)


def _manager_from_request(data: dict):
	"""Authenticate the manager PIN carried by a manager panel request."""
	pin = data.get("manager_pin") or frappe.form_dict.get("manager_pin") or get_pin(data)
	return authenticate_manager(pin)


@frappe.whitelist(methods=["POST"])
def timeclock_manager_authenticate():
	"""
	Unlock the "Timeclock Edit" / "Add" sections with a Manager role PIN.

	Request
	-------
	manager_pin (required): 6-digit PIN of an employee with role Manager

	Response
	--------
	manager details plus the employee list for the filter panel dropdown.
	"""
	data = get_request_data()
	manager = _manager_from_request(data)
	return {"manager": serialize_employee(manager), "employees": get_employee_options()}


@frappe.whitelist(methods=["POST"])
def timeclock_employee_list():
	"""
	Employees for the manager filter panel dropdown.

	Request
	-------
	manager_pin (required)
	include_inactive (optional): include deactivated employees
	"""
	data = get_request_data()
	_manager_from_request(data)
	include_inactive = cint(data.get("include_inactive"))
	return {"employees": get_employee_options(include_inactive=include_inactive)}


@frappe.whitelist(methods=["POST"])
def timeclock_get_record():
	"""
	Load the timeclock record of an employee for a business date.

	Request
	-------
	manager_pin (required)
	employee (required): ArcPOS Employee id
	business_date (required)
	"""
	data = get_request_data()
	_manager_from_request(data)
	return get_record_for_manager(data.get("employee"), get_business_date_param(data))


@frappe.whitelist(methods=["POST"])
def timeclock_update_record():
	"""
	Manually set or edit the check in / check out timestamps of an existing record.

	Flags the record as modified, logs the manager, and recalculates paid hours.

	Request
	-------
	manager_pin (required)
	employee (required), business_date (required)
	first_check_in (optional), last_check_out (optional)
	"""
	data = get_request_data()
	manager = _manager_from_request(data)
	return update_record(
		manager,
		data.get("employee"),
		get_business_date_param(data),
		first_check_in=data.get("first_check_in"),
		last_check_out=data.get("last_check_out"),
	)


@frappe.whitelist(methods=["POST"])
def timeclock_add_entry():
	"""
	Create a timeclock entry for a business date the employee never clocked.

	The created record is flagged as a manual entry.

	Request
	-------
	manager_pin (required)
	employee (required), business_date (required)
	first_check_in (required), last_check_out (optional)
	"""
	data = get_request_data()
	manager = _manager_from_request(data)
	return create_manual_entry(
		manager,
		data.get("employee"),
		get_business_date_param(data),
		data.get("first_check_in"),
		last_check_out=data.get("last_check_out"),
	)
