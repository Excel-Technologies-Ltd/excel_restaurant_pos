import datetime

import frappe
from frappe.utils import get_time, getdate, nowdate, nowtime


def _time_to_seconds(value):
	if not value:
		return None
	if isinstance(value, datetime.timedelta):
		return int(value.total_seconds())
	if isinstance(value, datetime.time):
		return value.hour * 3600 + value.minute * 60 + value.second

	time_obj = get_time(value)
	return time_obj.hour * 3600 + time_obj.minute * 60 + time_obj.second


def _is_within_date_range(starts_on, till_date, current_date):
	if not starts_on and not till_date:
		return True
	if starts_on and current_date < getdate(starts_on):
		return False
	if till_date and current_date > getdate(till_date):
		return False
	return True


def _is_within_time_slots(time_slots, current_time):
	if not time_slots:
		return True

	current_seconds = _time_to_seconds(current_time)
	for slot in time_slots:
		start = _time_to_seconds(slot.get("start_time"))
		end = _time_to_seconds(slot.get("end_time"))
		if start is None or end is None:
			continue
		if start <= end:
			if start <= current_seconds <= end:
				return True
		elif current_seconds >= start or current_seconds <= end:
			return True
	return False


def filter_visible_item_groups(item_group_list, current_date=None, current_time=None):
	"""Filter item groups by configured visibility date range and time slots."""
	if not item_group_list:
		return item_group_list

	current_date = getdate(current_date or nowdate())
	current_time = current_time or nowtime()

	item_group_names = [row["name"] for row in item_group_list if row.get("name")]
	if not item_group_names:
		return item_group_list

	visibility_rows = frappe.get_all(
		"Item Group",
		filters={"name": ["in", item_group_names]},
		fields=["name", "custom_visibility_starts_on", "custom_visibility_till_date"],
	)
	visibility_by_name = {row["name"]: row for row in visibility_rows}

	time_slot_rows = frappe.get_all(
		"Visibility Time Slot",
		filters={
			"parent": ["in", item_group_names],
			"parenttype": "Item Group",
			"parentfield": "custom_visibility_time_bound",
		},
		fields=["parent", "start_time", "end_time"],
	)
	time_slots_by_parent = {}
	for slot in time_slot_rows:
		time_slots_by_parent.setdefault(slot["parent"], []).append(slot)

	visible_item_groups = []
	for item_group in item_group_list:
		name = item_group.get("name")
		if not name:
			visible_item_groups.append(item_group)
			continue

		visibility = visibility_by_name.get(name, {})
		starts_on = visibility.get("custom_visibility_starts_on")
		till_date = visibility.get("custom_visibility_till_date")
		time_slots = time_slots_by_parent.get(name, [])

		if not starts_on and not till_date and not time_slots:
			visible_item_groups.append(item_group)
			continue

		if not _is_within_date_range(starts_on, till_date, current_date):
			continue
		if not _is_within_time_slots(time_slots, current_time):
			continue

		visible_item_groups.append(item_group)

	return visible_item_groups
