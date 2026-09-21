"""
Public API for creating table reservations from website/guest users.
"""

import frappe
from frappe import _
import json
from frappe.utils import add_days, add_to_date, cint, get_time, getdate, now_datetime, nowdate

# Anti-spam limits. The form lives on the restaurant's own website, so these
# are the protection that works without changing it; the per-IP budget is in
# utils/rate_limit.py.
MAX_GUESTS = 20
MAX_DAYS_AHEAD = 60
# Pending, upcoming reservations one email address or phone number may hold.
MAX_PENDING_PER_CONTACT = 2
# Website reservations accepted per hour across all callers. Past this, staff
# get one alert instead of a push per fake booking.
SITE_HOURLY_LIMIT = 30
FIELD_LENGTHS = {
    "guest_name": 100,
    "email": 140,
    "phone_number": 30,
    "requested_from": 50,
    "special_requests": 1000,
}
FLOOD_ALERT_CACHE_KEY = "arcpos:reservation_flood_alerted"


@frappe.whitelist(allow_guest=True)
def create_reservation():
    """
    Create a new table reservation from guest submission.

    Required Parameters:
    - guest_name: Name of the guest
    - email: Email address
    - phone_number: Phone number
    - reservation_date: Date of reservation (YYYY-MM-DD)
    - reservation_time: Time of reservation (HH:MM:SS)
    - number_of_guests: Number of guests (integer)

    Optional Parameters:
    - special_requests: Any special requests from guest

    Returns:
        dict: Success message with reservation details
    """
    try:
        # Get and validate required parameters
        guest_name = frappe.form_dict.get("guest_name")
        email = frappe.form_dict.get("email")
        phone_number = frappe.form_dict.get("phone_number")
        reservation_date = frappe.form_dict.get("reservation_date")
        reservation_time = frappe.form_dict.get("reservation_time")
        number_of_guests = frappe.form_dict.get("number_of_guests")
        requested_from = frappe.form_dict.get("requested_from")

        # Validate required fields
        if not guest_name:
            frappe.throw(_("Guest name is required"))

        if not email:
            frappe.throw(_("Email is required"))

        if not phone_number:
            frappe.throw(_("Phone number is required"))

        if not reservation_date:
            frappe.throw(_("Reservation date is required"))

        if not reservation_time:
            frappe.throw(_("Reservation time is required"))

        if not number_of_guests:
            frappe.throw(_("Number of guests is required"))

        if not requested_from:
            frappe.throw(_("Requested from is required"))

        # Validate email format
        from frappe.utils import validate_email_address

        if not validate_email_address(email, throw=False):
            frappe.throw(_("Invalid email address"))

        # Validate number of guests is a positive integer
        try:
            number_of_guests = int(number_of_guests)
            if number_of_guests <= 0:
                frappe.throw(_("Number of guests must be greater than 0"))
        except ValueError:
            frappe.throw(_("Number of guests must be a valid number"))

        # Validate reservation date is not in the past
        if getdate(reservation_date) < getdate(nowdate()):
            frappe.throw(_("Reservation date cannot be in the past"))

        # Get optional parameters
        special_requests = frappe.form_dict.get("special_requests", "") or ""

        email = email.strip().lower()
        _check_reservation_limits(
            guest_name=guest_name,
            email=email,
            phone_number=phone_number,
            reservation_date=reservation_date,
            reservation_time=reservation_time,
            number_of_guests=number_of_guests,
            requested_from=requested_from,
            special_requests=special_requests,
        )

        # Create reservation document
        reservation = frappe.get_doc(
            {
                "doctype": "Table Reservation",
                "guest_name": guest_name,
                "email": email,
                "phone_number": phone_number,
                "reservation_date": reservation_date,
                "reservation_time": reservation_time,
                "number_of_guests": number_of_guests,
                "special_requests": special_requests,
                "status": "Pending",
                "requested_from": requested_from,
            }
        )

        # Save the reservation (ignore permissions for guest users)
        reservation.insert(ignore_permissions=True)

        # Commit the transaction
        frappe.db.commit()

        # Return success response
        return {
            "success": True,
            "message": _(
                "Reservation request submitted successfully! You will receive a confirmation email once we confirm your reservation."
            ),
            "reservation": {
                "name": reservation.name,
                "guest_name": reservation.guest_name,
                "email": reservation.email,
                "phone_number": reservation.phone_number,
                "reservation_date": frappe.utils.format_date(
                    reservation.reservation_date, "dd MMM yyyy"
                ),
                "reservation_time": frappe.utils.format_time(
                    reservation.reservation_time
                ),
                "number_of_guests": reservation.number_of_guests,
                "requested_from": reservation.requested_from,
                "status": reservation.status,
            },
        }

    except frappe.ValidationError as e:
        frappe.clear_messages()
        return {"success": False, "message": str(e)}

    except Exception as e:
        frappe.log_error(
            "Table Reservation API Error",
            f"Error creating reservation: {str(e)}",
        )
        frappe.clear_messages()
        return {
            "success": False,
            "message": _(
                "An error occurred while creating your reservation. Please try again or contact us directly."
            ),
        }


def _check_reservation_limits(**fields):
    """Refuse what no real guest sends, and more bookings than any one person makes."""
    for fieldname, limit in FIELD_LENGTHS.items():
        if len(str(fields.get(fieldname) or "")) > limit:
            frappe.throw(_("{0} is too long").format(fieldname.replace("_", " ").capitalize()))

    if fields["number_of_guests"] > MAX_GUESTS:
        frappe.throw(
            _("For more than {0} guests, please call us to arrange your reservation.").format(MAX_GUESTS)
        )

    if getdate(fields["reservation_date"]) > getdate(add_days(nowdate(), MAX_DAYS_AHEAD)):
        frappe.throw(_("Reservations can be made up to {0} days ahead.").format(MAX_DAYS_AHEAD))

    try:
        get_time(fields["reservation_time"])
    except Exception:
        frappe.throw(_("Invalid reservation time"))

    email, phone = fields["email"], fields["phone_number"]
    upcoming = {"reservation_date": [">=", nowdate()]}

    if frappe.db.exists(
        "Table Reservation",
        {
            "email": email,
            "reservation_date": fields["reservation_date"],
            "reservation_time": fields["reservation_time"],
            "status": ["in", ["Pending", "Confirmed"]],
        },
    ):
        frappe.throw(_("You already have a reservation at this time."))

    pending = frappe.get_all(
        "Table Reservation",
        filters={**upcoming, "status": "Pending"},
        or_filters={"email": email, "phone_number": phone},
        pluck="name",
        limit=MAX_PENDING_PER_CONTACT,
    )
    if len(pending) >= MAX_PENDING_PER_CONTACT:
        frappe.throw(
            _("You already have reservation requests waiting for confirmation. Please wait for us to confirm them, or call us.")
        )

    # Counted by owner rather than requested_from, which the caller chooses.
    recent = frappe.db.count(
        "Table Reservation",
        {"owner": "Guest", "creation": [">=", add_to_date(now_datetime(), hours=-1)]},
    )
    if recent >= SITE_HOURLY_LIMIT:
        _alert_staff_of_flood(recent)
        frappe.throw(
            _("We are receiving an unusually high number of reservation requests. Please try again later or call us.")
        )


def _alert_staff_of_flood(recent):
    """Tell reservation staff once an hour, instead of one push per fake booking."""
    # expires=True: an expiring key must not be cached in frappe.local, or a
    # miss read before set_value keeps reading as a miss.
    if frappe.cache().get_value(FLOOD_ALERT_CACHE_KEY, expires=True):
        return
    frappe.cache().set_value(FLOOD_ALERT_CACHE_KEY, 1, expires_in_sec=3600)

    frappe.log_error(
        title="Reservation flood",
        message=f"{recent} website reservations in the last hour; new ones refused. ip={getattr(frappe.local, 'request_ip', None)}",
    )
    staff = frappe.get_all(
        "Has Role",
        filters={"role": "ArcPOS Reservation User", "parenttype": "User", "parent": ["not in", ["Administrator", "Guest"]]},
        pluck="parent",
        distinct=True,
    )
    for user in staff:
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "for_user": user,
                "from_user": "Administrator",
                "subject": "Unusual number of website reservations",
                "email_content": (
                    f"{recent} reservation requests arrived from the website in the last hour. "
                    "New requests are being refused for now; please review the pending ones."
                ),
                "type": "Alert",
            }
        ).insert(ignore_permissions=True)


@frappe.whitelist(allow_guest=True)
def get_available_slots():
    """
    Get available reservation time slots for a given date.

    Parameters:
    - reservation_date: Date to check (YYYY-MM-DD)

    Returns:
        dict: Available time slots
    """
    try:
        reservation_date = frappe.form_dict.get("reservation_date")

        if not reservation_date:
            frappe.throw(_("Reservation date is required"))

        # Validate reservation date is not in the past
        from frappe.utils import getdate, nowdate

        if getdate(reservation_date) < getdate(nowdate()):
            frappe.throw(_("Cannot check slots for past dates"))

        # Get all reservations for the date
        reservations = frappe.get_all(
            "Table Reservation",
            filters={
                "reservation_date": reservation_date,
                "status": ["in", ["Pending", "Confirmed"]],
            },
            fields=["reservation_time", "number_of_guests"],
        )

        # Define available time slots (restaurant hours)
        # This can be configured in ArcPOS Settings if needed
        available_slots = [
            {"time": "11:00:00", "label": "11:00 AM"},
            {"time": "11:30:00", "label": "11:30 AM"},
            {"time": "12:00:00", "label": "12:00 PM"},
            {"time": "12:30:00", "label": "12:30 PM"},
            {"time": "13:00:00", "label": "1:00 PM"},
            {"time": "13:30:00", "label": "1:30 PM"},
            {"time": "14:00:00", "label": "2:00 PM"},
            {"time": "17:00:00", "label": "5:00 PM"},
            {"time": "17:30:00", "label": "5:30 PM"},
            {"time": "18:00:00", "label": "6:00 PM"},
            {"time": "18:30:00", "label": "6:30 PM"},
            {"time": "19:00:00", "label": "7:00 PM"},
            {"time": "19:30:00", "label": "7:30 PM"},
            {"time": "20:00:00", "label": "8:00 PM"},
            {"time": "20:30:00", "label": "8:30 PM"},
            {"time": "21:00:00", "label": "9:00 PM"},
        ]

        # Count reservations per slot
        reservation_counts = {}
        for res in reservations:
            time_key = str(res.reservation_time)
            reservation_counts[time_key] = reservation_counts.get(time_key, 0) + 1

        # Mark slots as available or full (max 10 reservations per slot as example)
        max_reservations_per_slot = 10
        for slot in available_slots:
            slot["available"] = (
                reservation_counts.get(slot["time"], 0) < max_reservations_per_slot
            )
            slot["reserved_count"] = reservation_counts.get(slot["time"], 0)

        return {
            "success": True,
            "date": frappe.utils.format_date(reservation_date, "dd MMM yyyy"),
            "slots": available_slots,
        }

    except Exception as e:
        frappe.log_error(
            "Table Reservation API Error",
            f"Error fetching available slots: {str(e)}",
        )
        return {"success": False, "message": str(e)}
