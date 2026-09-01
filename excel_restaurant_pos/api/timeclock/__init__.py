"""Employee timeclock API endpoints."""

from .authenticate import authenticate_timeclock_pin
from .clock import timeclock_check_in, timeclock_check_out
from .manager import (
	timeclock_add_entry,
	timeclock_employee_list,
	timeclock_get_record,
	timeclock_manager_authenticate,
	timeclock_update_record,
)

__all__ = [
	"authenticate_timeclock_pin",
	"timeclock_add_entry",
	"timeclock_check_in",
	"timeclock_check_out",
	"timeclock_employee_list",
	"timeclock_get_record",
	"timeclock_manager_authenticate",
	"timeclock_update_record",
]

timeclock_api_routes = {
	"api.timeclock.authenticate": "excel_restaurant_pos.api.timeclock.authenticate_timeclock_pin",
	"api.timeclock.check_in": "excel_restaurant_pos.api.timeclock.timeclock_check_in",
	"api.timeclock.check_out": "excel_restaurant_pos.api.timeclock.timeclock_check_out",
	"api.timeclock.manager_authenticate": "excel_restaurant_pos.api.timeclock.timeclock_manager_authenticate",
	"api.timeclock.employees": "excel_restaurant_pos.api.timeclock.timeclock_employee_list",
	"api.timeclock.get_record": "excel_restaurant_pos.api.timeclock.timeclock_get_record",
	"api.timeclock.update_record": "excel_restaurant_pos.api.timeclock.timeclock_update_record",
	"api.timeclock.add_entry": "excel_restaurant_pos.api.timeclock.timeclock_add_entry",
}
