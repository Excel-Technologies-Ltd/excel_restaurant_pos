import frappe
from frappe import _
from frappe.utils import random_string, now
from jinja2 import Template
import json
from excel_restaurant_pos.shared.arcpos_settings.system_settings import default_system_settings
from excel_restaurant_pos.shared.email_templates.get_template import template_by_name
from excel_restaurant_pos.shared.web_customer import ensure_customer_for_user, web_customer_roles

@frappe.whitelist(allow_guest=True)
def sign_up(email, mobile_no, full_name, password, redirect_to=None):
    """Register user with OTP verification"""

    # Check if user already exists
    if frappe.db.exists("User", email):
        user = frappe.db.get_value("User", email, ["enabled"], as_dict=True)
        if user.enabled:
            return {
                "success": False,
                "message": _("User already registered")
            }
        else:
            return {
                "success": False,
                "message": _("User registered but not verified. Please contact administrator.")
            }

    # Rate limiting check
    if frappe.db.sql("""select count(*) from tabUser where
        HOUR(TIMEDIFF(CURRENT_TIMESTAMP, TIMESTAMP(modified))) < 1""")[0][0] > 300:
        return {
            "success": False,
            "message": _("Too many sign-ups recently. Please try again later.")
        }

    # Generate unique verification key and OTP
    verification_key = frappe.generate_hash(length=32)
    otp = str(random_string(6)).upper()  # 6-digit alphanumeric OTP

    # Store user data in cache for 5 minutes (300 seconds)
    cache_data = {
        "email": email,
        "full_name": full_name,
        "mobile_no": mobile_no,
        "password": password,
        "redirect_to": redirect_to,
        "otp": otp,
        "created_at": now()
    }

    cache_key = f"signup_verification:{verification_key}"
    frappe.cache().set_value(cache_key, json.dumps(cache_data), expires_in_sec=300)

    # Send OTP via email
    send_otp_email(email, full_name, otp)

    return {
        "success": True,
        "message": _("OTP sent to your email. Please verify within 5 minutes."),
        "verification_key": verification_key
    }


def send_otp_email(email, full_name, otp):
    """Send OTP verification email"""
    first_name = full_name.split()[0] if full_name else email.split('@')[0]

    # Try to get custom email template
    try:
        template_name = default_system_settings().registration_template
        template = template_by_name(template_name)
        # Render the template with OTP
        html_content = Template(template.response_html).render({
            "otp": otp,
            "first_name": first_name,
            "email": email
        })

        subject = template.subject or _("Verify Your Email - OTP")
    except:
        # Fallback to simple email if template doesn't exist
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <p>Hi {first_name},</p>
            <p>Your OTP for email verification is:</p>
            <div style="background: #f5f5f5; padding: 20px; text-align: center; margin: 20px 0;">
                <h1 style="color: #667eea; letter-spacing: 5px; margin: 0;">{otp}</h1>
            </div>
            <p>This OTP will expire in 5 minutes.</p>
            <p>If you didn't request this, please ignore this email.</p>
            
        </div>
        """
        subject = _("Verify Your Email - OTP")

    frappe.sendmail(
        recipients=email,
        subject=subject,
        message=html_content,
        header=[_("Email Verification"), "blue"],
        delayed=False,
        retry=3,
        now=True
    )


@frappe.whitelist(allow_guest=True)
def verify_otp(verification_key, otp):
    """Verify OTP and create user account"""

    # Get cached data
    cache_key = f"signup_verification:{verification_key}"
    cached_data = frappe.cache().get_value(cache_key)

    print(cached_data)

    if not cached_data:
        return {
            "success": False,
            "message": _("Verification link expired or invalid. Please sign up again.")
        }

    # Parse cached data
    try:
        user_data = json.loads(cached_data)
    except:
        return {
            "success": False,
            "message": _("Invalid verification data. Please sign up again.")
        }

    # Verify OTP (case-insensitive)
    if user_data.get("otp", "").upper() != otp.upper():
        return {
            "success": False,
            "message": _("Invalid OTP. Please try again.")
        }

    # Create user account
    try:
        user = frappe.get_doc({
            "doctype": "User",
            "email": user_data["email"],
            "first_name": user_data["full_name"],
            "mobile_no": user_data.get("mobile_no"),
            "enabled": 1,  # User is enabled after OTP verification
            "new_password": user_data["password"],
            "user_type": "Website User"
        })
        user.flags.ignore_permissions = True
        user.flags.ignore_password_policy = True
        user.flags.no_welcome_mail = True
        user.insert()

        # Roles and Customer come from the same place as Google sign-up, so a
        # web account is the same account however it was made. The Customer's
        # User Permissions are now ensured even when a Customer with this email
        # already existed -- they used to be skipped, leaving the account
        # unrestricted.
        user.add_roles(*web_customer_roles())
        ensure_customer_for_user(user, mobile_no=user_data.get("mobile_no"))

        # Clear cache
        frappe.cache().delete_value(cache_key)

        # Set redirect URL if provided
        redirect_url = user_data.get("redirect_to") or "/app"

        return {
            "success": True,
            "message": _("Account verified successfully! You can now login."),
            "email": user.email,
            "redirect_to": redirect_url
        }

    except Exception as e:
        # Undo the User too. It is inserted, and given Sales User, before the
        # Customer is created; without this, a failure there committed an account
        # with a password, Sales User and no User Permission -- able to read
        # every invoice. Rolled back first, so the log entry below survives.
        frappe.db.rollback()
        frappe.log_error(f"User creation failed: {str(e)}", "OTP Verification Error")
        print(e)
        print("Error creating user", str(e))
        return {
            "success": False,
            "message": _("Failed to create account. Please try again or contact support.")
        }


@frappe.whitelist(allow_guest=True)
def resend_otp(verification_key):
    """Resend OTP for verification"""

    # Get cached data
    cache_key = f"signup_verification:{verification_key}"
    cached_data = frappe.cache().get_value(cache_key)

    if not cached_data:
        return {
            "success": False,
            "message": _("Verification session expired. Please sign up again.")
        }

    try:
        user_data = json.loads(cached_data)
    except:
        return {
            "success": False,
            "message": _("Invalid verification data. Please sign up again.")
        }

    # Generate new OTP
    new_otp = str(random_string(6)).upper()
    user_data["otp"] = new_otp
    user_data["created_at"] = now()

    # Update cache with new OTP and reset expiry to 5 minutes
    frappe.cache().set_value(cache_key, json.dumps(user_data), expires_in_sec=300)

    # Send new OTP
    send_otp_email(user_data["email"], user_data["full_name"], new_otp)

    return {
        "success": True,
        "message": _("New OTP sent to your email.")
    }
