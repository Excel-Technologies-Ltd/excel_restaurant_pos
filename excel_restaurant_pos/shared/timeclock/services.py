"""Employee timeclock: business day rules, check in / check out, manager overrides."""

from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate, now_datetime

from excel_restaurant_pos.shared.timeclock.pin import hash_pin, normalize_pin

TRACKING_DOCTYPE = "Employee Timeclock Tracking"
EMPLOYEE_DOCTYPE = "ArcPOS Employee"
MANAGER_ROLE = "Manager"

# A business day runs from 04:01 AM (day T) through 04:00 AM (day T+1), so any
# timestamp at or before 04:00 AM belongs to the previous business date.
BUSINESS_DAY_END = datetime.time(4, 0, 0)

EMPLOYEE_FIELDS = ["name", "employee_name", "role", "is_active"]

# Brute force guard for the numpad: PINs are only 6 digits.
PIN_ATTEMPT_LIMIT = 10
PIN_ATTEMPT_WINDOW = 300


# ---------------------------------------------------------------------------
# Business day helpers
# ---------------------------------------------------------------------------


def get_business_date(moment=None) -> datetime.date:
	"""Return the business date that a datetime falls into."""
	moment = get_datetime(moment) if moment else now_datetime()
	if moment.time() <= BUSINESS_DAY_END:
		return moment.date() - datetime.timedelta(days=1)
	return moment.date()


def get_business_day_window(business_date) -> tuple[datetime.datetime, datetime.datetime]:
	"""Return the (start, end) datetimes of a business date."""
	business_date = getdate(business_date)
	start = datetime.datetime.combine(business_date, BUSINESS_DAY_END) + datetime.timedelta(seconds=1)
	end = datetime.datetime.combine(business_date + datetime.timedelta(days=1), BUSINESS_DAY_END)
	return start, end


def compute_paid_hours(first_check_in, last_check_out) -> float:
	"""Hours between check in and check out, rounded to 2 decimals."""
	if not first_check_in or not last_check_out:
		return 0.0

	seconds = (get_datetime(last_check_out) - get_datetime(first_check_in)).total_seconds()
	if seconds <= 0:
		return 0.0
	return flt(seconds / 3600.0, 2)


def get_timeclock_cost() -> float:
	"""Hourly timeclock cost configured in ArcPOS Settings."""
	return flt(frappe.db.get_single_value("ArcPOS Settings", "timeclock_cost"))


# ---------------------------------------------------------------------------
# PIN authentication
# ---------------------------------------------------------------------------


def _pin_attempt_key() -> str:
	ip = getattr(frappe.local, "request_ip", None) or "unknown"
	return f"timeclock:pin-attempts:{frappe.session.user}:{ip}"


def _guard_pin_attempts():
	if flt(frappe.cache().get_value(_pin_attempt_key())) >= PIN_ATTEMPT_LIMIT:
		frappe.throw(_("Too many invalid PIN attempts. Please try again later."), frappe.AuthenticationError)


def _record_failed_attempt():
	key = _pin_attempt_key()
	attempts = flt(frappe.cache().get_value(key)) + 1
	frappe.cache().set_value(key, attempts, expires_in_sec=PIN_ATTEMPT_WINDOW)


def authenticate_employee(pin, role: str | None = None) -> frappe._dict:
	"""Resolve an active employee from a 6-digit PIN, optionally requiring a role."""
	pin = normalize_pin(pin)
	_guard_pin_attempts()

	employee = frappe.db.get_value(
		EMPLOYEE_DOCTYPE, {"pin": hash_pin(pin), "is_active": 1}, EMPLOYEE_FIELDS, as_dict=True
	)
	if not employee:
		_record_failed_attempt()
		frappe.throw(_("Invalid PIN"), frappe.AuthenticationError)

	frappe.cache().delete_value(_pin_attempt_key())

	if role and employee.role != role:
		frappe.throw(_("This action requires a {0} PIN").format(role), frappe.PermissionError)

	return employee


def authenticate_manager(pin) -> frappe._dict:
	"""Resolve an active manager from a 6-digit PIN."""
	return authenticate_employee(pin, role=MANAGER_ROLE)


# ---------------------------------------------------------------------------
# Tracking records
# ---------------------------------------------------------------------------


def get_tracking_record(employee, business_date, for_update: bool = False):
	"""Return the tracking record of an employee for a business date, if any."""
	name = frappe.db.get_value(
		TRACKING_DOCTYPE, {"employee": employee, "business_date": getdate(business_date)}, "name"
	)
	if not name:
		return None
	return frappe.get_doc(TRACKING_DOCTYPE, name, for_update=for_update)


def get_open_earlier_record(employee, business_date):
	"""Return the most recent earlier record left without a check out, if any."""
	records = frappe.get_all(
		TRACKING_DOCTYPE,
		filters={
			"employee": employee,
			"business_date": ("<", getdate(business_date)),
			"last_check_out": ("is", "not set"),
		},
		fields=["name", "business_date", "first_check_in"],
		order_by="business_date desc",
		limit=1,
	)
	return records[0] if records else None


def serialize_record(doc) -> dict | None:
	"""Shape a tracking record for the POS."""
	if not doc:
		return None

	return {
		"name": doc.name,
		"employee": doc.employee,
		"employee_name": doc.employee_name,
		"business_date": str(getdate(doc.business_date)),
		"first_check_in": str(doc.first_check_in) if doc.first_check_in else None,
		"last_check_out": str(doc.last_check_out) if doc.last_check_out else None,
		"total_paid_hours": flt(doc.total_paid_hours, 2),
		"timeclock_cost": flt(doc.timeclock_cost),
		"total_payment": flt(doc.total_payment),
		"is_modified": bool(doc.is_modified),
		"manual_entry": bool(doc.manual_entry),
		"modified_by_manager": doc.modified_by_manager,
	}


def serialize_employee(employee) -> dict:
	return {
		"employee": employee.name,
		"employee_name": employee.employee_name,
		"role": employee.role,
		"is_manager": employee.role == MANAGER_ROLE,
	}


# ---------------------------------------------------------------------------
# State and actions
# ---------------------------------------------------------------------------


def get_timeclock_state(employee) -> dict:
	"""Determine which action the POS should offer for an employee."""
	business_date = get_business_date()
	record = get_tracking_record(employee.name, business_date)
	blocking_record = get_open_earlier_record(employee.name, business_date)

	if blocking_record:
		action = "blocked"
		message = _("Check out is missing for {0}. A manager must fix it before a new entry can be made.").format(
			str(getdate(blocking_record.business_date))
		)
	elif not record or not record.first_check_in:
		action = "check_in"
		message = None
	else:
		action = "check_out"
		message = None

	return {
		**serialize_employee(employee),
		"business_date": str(business_date),
		"action": action,
		"can_check_in": action == "check_in",
		"can_check_out": action == "check_out",
		"message": message,
		"open_record": {
			"name": blocking_record.name,
			"business_date": str(getdate(blocking_record.business_date)),
			"first_check_in": str(blocking_record.first_check_in) if blocking_record.first_check_in else None,
		}
		if blocking_record
		else None,
		"record": serialize_record(record),
	}


def check_in(employee) -> dict:
	"""Record the first check in of an employee for the current business date."""
	business_date = get_business_date()

	blocking_record = get_open_earlier_record(employee.name, business_date)
	if blocking_record:
		frappe.throw(
			_("Check out is missing for {0}. A manager must fix it before a new entry can be made.").format(
				str(getdate(blocking_record.business_date))
			),
			frappe.ValidationError,
		)

	record = get_tracking_record(employee.name, business_date, for_update=True)
	if record and record.first_check_in:
		frappe.throw(_("{0} is already checked in for {1}").format(employee.employee_name, business_date))

	if not record:
		record = frappe.new_doc(TRACKING_DOCTYPE)
		record.employee = employee.name
		record.business_date = business_date

	record.first_check_in = now_datetime()
	record.save(ignore_permissions=True)

	return {**serialize_employee(employee), "action": "check_out", "record": serialize_record(record)}


def check_out(employee) -> dict:
	"""Record (or replace) the last check out of an employee for the current business date."""
	business_date = get_business_date()
	record = get_tracking_record(employee.name, business_date, for_update=True)

	if not record or not record.first_check_in:
		frappe.throw(_("{0} has not checked in for {1}").format(employee.employee_name, business_date))

	record.last_check_out = now_datetime()
	record.save(ignore_permissions=True)

	return {**serialize_employee(employee), "action": "check_out", "record": serialize_record(record)}


# ---------------------------------------------------------------------------
# Manager overrides
# ---------------------------------------------------------------------------


def _parse_datetime(value, label: str):
	if value in (None, ""):
		return None
	try:
		return get_datetime(value)
	except Exception:
		frappe.throw(_("{0} is not a valid date and time").format(label), frappe.ValidationError)


def get_employee_options(include_inactive: bool = False) -> list[dict]:
	"""Employees for the manager filter panel dropdown."""
	filters = {} if include_inactive else {"is_active": 1}
	return frappe.get_all(
		EMPLOYEE_DOCTYPE,
		filters=filters,
		fields=["name as employee", "employee_name", "role", "is_active"],
		order_by="employee_name asc",
	)


def get_record_for_manager(employee, business_date) -> dict:
	"""Load the tracking record a manager asked to edit."""
	employee = _validate_employee(employee)
	business_date = getdate(business_date)
	record = get_tracking_record(employee.name, business_date)

	return {
		**serialize_employee(employee),
		"business_date": str(business_date),
		"record": serialize_record(record),
	}


def update_record(manager, employee, business_date, first_check_in=None, last_check_out=None) -> dict:
	"""Manager edit of an existing record: flags it modified and recalculates totals."""
	employee = _validate_employee(employee)
	business_date = getdate(business_date)

	record = get_tracking_record(employee.name, business_date, for_update=True)
	if not record:
		frappe.throw(
			_("No timeclock entry found for {0} on {1}").format(employee.employee_name, business_date),
			frappe.DoesNotExistError,
		)

	if first_check_in is not None:
		record.first_check_in = _parse_datetime(first_check_in, _("First Check In"))
	if last_check_out is not None:
		record.last_check_out = _parse_datetime(last_check_out, _("Last Check Out"))

	if not record.first_check_in:
		frappe.throw(_("First Check In is required"), frappe.MandatoryError)

	record.is_modified = 1
	record.modified_by_manager = manager.name
	record.save(ignore_permissions=True)

	return {**serialize_employee(employee), "record": serialize_record(record)}


def create_manual_entry(manager, employee, business_date, first_check_in, last_check_out=None) -> dict:
	"""Manager created entry for a business date the employee never clocked."""
	employee = _validate_employee(employee)
	business_date = getdate(business_date)

	if get_tracking_record(employee.name, business_date):
		frappe.throw(
			_("A timeclock entry already exists for {0} on {1}").format(employee.employee_name, business_date),
			frappe.DuplicateEntryError,
		)

	first_check_in = _parse_datetime(first_check_in, _("First Check In"))
	if not first_check_in:
		frappe.throw(_("First Check In is required"), frappe.MandatoryError)

	record = frappe.new_doc(TRACKING_DOCTYPE)
	record.employee = employee.name
	record.business_date = business_date
	record.first_check_in = first_check_in
	record.last_check_out = _parse_datetime(last_check_out, _("Last Check Out"))
	record.manual_entry = 1
	record.modified_by_manager = manager.name
	record.insert(ignore_permissions=True)

	return {**serialize_employee(employee), "record": serialize_record(record)}


def _validate_employee(employee) -> frappe._dict:
	"""Resolve an employee id coming from a manager panel request."""
	if not employee:
		frappe.throw(_("Employee is required"), frappe.MandatoryError)

	details = frappe.db.get_value(EMPLOYEE_DOCTYPE, employee, EMPLOYEE_FIELDS, as_dict=True)
	if not details:
		frappe.throw(_("Employee {0} does not exist").format(employee), frappe.DoesNotExistError)
	return details
