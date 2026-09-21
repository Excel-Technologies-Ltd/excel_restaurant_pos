import frappe
from frappe import _
from frappe.utils import cint
from frappe.twofactor import should_run_2fa, authenticate_for_2factor, confirm_otp_token, get_cached_user_pass
from frappe.sessions import clear_sessions
from excel_restaurant_pos.utils.jwt_auth import generate_access_token, generate_refresh_token, revoke_all_user_tokens, add_user_session
from excel_restaurant_pos.utils.error_handler import throw_error, ErrorCode, success_response
from excel_restaurant_pos.shared.arcpos_settings.system_settings import default_system_settings
from excel_restaurant_pos.shared.antispam import check_honeypot, turnstile
from excel_restaurant_pos.shared.antispam.forms import LOGIN
from excel_restaurant_pos.shared.customer_access import is_staff


def _refuse_bad_credentials():
	throw_error(
		ErrorCode.INVALID_CREDENTIALS,
		_("Invalid username or password"),
		http_status_code=401
	)


@frappe.whitelist(allow_guest=True)
def login(user, pwd, **guards):
	"""Authenticate user with email/username and password using JWT tokens

	Storefront accounts must also pass Turnstile; staff clients (pos-web, the
	mobile app) have no widget and are not asked. The storefront sends its token,
	which is checked before the password. A caller that sends none has the
	password checked first, and a storefront account is then refused with the
	very same wrong-password error -- so skipping the widget never tells a bot
	whose password it just guessed right.
	"""

	# Set user to Guest to avoid session resumption issues
	frappe.set_user("Guest")

	check_honeypot(guards, LOGIN)
	sent_token = turnstile.has_token(guards)
	if sent_token:
		turnstile.verify_turnstile(guards, LOGIN)

	# Use Frappe's find_by_credentials method which respects System Settings
	# This handles: allow_login_using_mobile_number, allow_login_using_user_name
	from frappe.core.doctype.user.user import User
	user_info = User.find_by_credentials(user, pwd, validate_password=True)

	if not user_info or not user_info.get("is_authenticated"):
		_refuse_bad_credentials()

	# Get the actual user email
	user = user_info.get("name")

	if turnstile.configured() and not sent_token and not is_staff(user):
		frappe.log_error(title="Login rejected: turnstile", message=f"no token supplied for storefront account {user}")
		_refuse_bad_credentials()

	# Get user document
	user_doc = frappe.get_doc("User", user)

	# Check if user is enabled
	if user_doc.enabled == 0:
		throw_error(
			ErrorCode.UNAUTHORIZED,
			_("User is disabled. Please contact your System Manager."),
			http_status_code=403
		)

	# Check if two-factor authentication is required
	if should_run_2fa(user):
		# Store password in form_dict for 2FA caching (required by Frappe's 2FA system)
		frappe.form_dict.pwd = pwd

		# Store credentials temporarily and trigger 2FA process
		authenticate_for_2factor(user)
		verification_data = frappe.local.response.get("verification", {})
		tmp_id = frappe.local.response.get("tmp_id")

		return success_response(
			message=_("Two-factor authentication required"),
			data={
				"requires_2fa": True,
				"tmp_id": tmp_id,
				"verification": verification_data,
				"email": user
			}
		)

	return issue_login_response(user, user_doc)


def issue_login_response(user, user_doc=None):
	"""Tokens and the login response for a user whose identity is established.

	Shared by password login and Google sign-in, so both return the same shape
	and enforce the same session limits.
	"""
	user_doc = user_doc or frappe.get_doc("User", user)

	# Get user roles
	user_permissions = frappe.get_roles(user)

	# Generate secure JWT tokens
	access_token = generate_access_token(user, expires_in_hours=int(default_system_settings().access_token_expiry or 1))
	refresh_token = generate_refresh_token(user, expires_in_days=int(default_system_settings().refresh_token_expiry or 7))

	# Check if System Settings has deny_multiple_sessions enabled
	deny_multiple = cint(frappe.db.get_single_value("System Settings", "deny_multiple_sessions"))
	frappe.logger().info(f"Login - deny_multiple_sessions setting: {deny_multiple}")

	# If deny_multiple_sessions is enabled, enforce user's simultaneous_sessions limit
	if deny_multiple:
		# Get user's simultaneous sessions limit
		simultaneous_sessions = int(user_doc.simultaneous_sessions or 0)
		frappe.logger().info(f"Login - User {user} has simultaneous_sessions: {simultaneous_sessions}")

		# If user has a session limit set (> 0), enforce it
		if simultaneous_sessions > 0:
			# Get token's issued-at timestamp
			import jwt as jwt_lib
			token_payload = jwt_lib.decode(access_token, options={"verify_signature": False})
			token_iat = token_payload.get("iat")

			frappe.logger().info(f"Login - Calling add_user_session for {user} with token_iat: {token_iat}, limit: {simultaneous_sessions}")

			# Track session and automatically revoke oldest sessions if limit exceeded
			revoked = add_user_session(user, token_iat, max_sessions=simultaneous_sessions)

			if revoked:
				frappe.logger().info(f"Revoked {len(revoked)} old session(s) for user {user} due to simultaneous session limit")

		# Clear all existing Frappe sessions for this user
		clear_sessions(user=user, force=True)

	# Clear session cookies to prevent session issues
	frappe.local.cookie_manager.set_cookie("sid", "", expires="Thu, 01 Jan 1970 00:00:00 GMT")
	frappe.local.cookie_manager.set_cookie("system_user", "", expires="Thu, 01 Jan 1970 00:00:00 GMT")

	customer_id = frappe.db.get_value("Customer", {"email_id": user}, "name")

	return success_response(
		message=_("Logged in successfully"),
		data={
			"user": {
				
				"first_name": user_doc.first_name,
				"last_name": user_doc.last_name,
				"full_name": user_doc.full_name,
				"email": user,
				"gender": user_doc.gender,
				"mobile_no": user_doc.mobile_no,
				"username": user_doc.username,
				"birth_date": user_doc.birth_date,
				"location": user_doc.location,
				"interests": user_doc.interest,
				"bio": user_doc.bio,
				"language": user_doc.language,
				"last_login": user_doc.last_login,
				"user_image": user_doc.user_image,
				"customer_id": customer_id

			},
			
			"access_token": access_token,
			"refresh_token": refresh_token,
			"token_type": "Bearer",
			"expires_in": 86400,  # 24 hours in seconds
			"permissions": user_permissions,
		}
	)


@frappe.whitelist(allow_guest=True)
def verify_2fa_and_login(otp, tmp_id):
	"""Verify 2FA OTP and complete login with JWT tokens"""

	# Set user to Guest
	frappe.set_user("Guest")

	# Validate inputs
	if not otp or not tmp_id:
		throw_error(
			ErrorCode.MISSING_REQUIRED_FIELD,
			_("OTP and temporary ID are required"),
			http_status_code=400
		)

	# Set form_dict for get_cached_user_pass to work
	frappe.form_dict.tmp_id = tmp_id
	frappe.form_dict.otp = otp

	# Get cached user credentials
	user, pwd = get_cached_user_pass()

	if not user:
		throw_error(
			ErrorCode.TOKEN_EXPIRED,
			_("Session expired. Please login again."),
			http_status_code=401
		)

	# Validate user exists
	if not frappe.db.exists("User", user):
		throw_error(
			ErrorCode.INVALID_CREDENTIALS,
			_("User does not exist"),
			http_status_code=401
		)

	# Create a mock login manager for OTP verification
	class MockLoginManager:
		def __init__(self, user):
			self.user = user

		def fail(self, message, user):
			throw_error(
				ErrorCode.INVALID_CREDENTIALS,
				message,
				http_status_code=401
			)

	login_manager = MockLoginManager(user)

	# Verify OTP token
	try:
		if not confirm_otp_token(login_manager, otp=otp, tmp_id=tmp_id):
			throw_error(
				ErrorCode.INVALID_CREDENTIALS,
				_("Invalid OTP"),
				http_status_code=401
			)
	except Exception as e:
		frappe.log_error(f"2FA verification failed: {str(e)}", "2FA Verification Error")
		throw_error(
			ErrorCode.INVALID_CREDENTIALS,
			_("Invalid or expired OTP. Please try again."),
			http_status_code=401
		)

	# OTP verified successfully, proceed with login
	user_doc = frappe.get_doc("User", user)

	# Check if user is enabled
	if user_doc.enabled == 0:
		throw_error(
			ErrorCode.UNAUTHORIZED,
			_("User is disabled. Please contact your System Manager."),
			http_status_code=403
		)

	# Get user roles
	user_permissions = frappe.get_roles(user)

	# Generate secure JWT tokens
	access_token = generate_access_token(user, expires_in_hours=int(default_system_settings().access_token_expiry or 1))
	refresh_token = generate_refresh_token(user, expires_in_days=int(default_system_settings().refresh_token_expiry or 7))

	# Check if System Settings has deny_multiple_sessions enabled
	deny_multiple = cint(frappe.db.get_single_value("System Settings", "deny_multiple_sessions"))
	frappe.logger().info(f"Login - deny_multiple_sessions setting: {deny_multiple}")

	# If deny_multiple_sessions is enabled, enforce user's simultaneous_sessions limit
	if deny_multiple:
		# Get user's simultaneous sessions limit
		simultaneous_sessions = int(user_doc.simultaneous_sessions or 0)
		frappe.logger().info(f"Login - User {user} has simultaneous_sessions: {simultaneous_sessions}")

		# If user has a session limit set (> 0), enforce it
		if simultaneous_sessions > 0:
			# Get token's issued-at timestamp
			import jwt as jwt_lib
			token_payload = jwt_lib.decode(access_token, options={"verify_signature": False})
			token_iat = token_payload.get("iat")

			frappe.logger().info(f"Login - Calling add_user_session for {user} with token_iat: {token_iat}, limit: {simultaneous_sessions}")

			# Track session and automatically revoke oldest sessions if limit exceeded
			revoked = add_user_session(user, token_iat, max_sessions=simultaneous_sessions)

			if revoked:
				frappe.logger().info(f"Revoked {len(revoked)} old session(s) for user {user} due to simultaneous session limit")

		# Clear all existing Frappe sessions for this user
		clear_sessions(user=user, force=True)

	# Clear session cookies to prevent session issues
	frappe.local.cookie_manager.set_cookie("sid", "", expires="Thu, 01 Jan 1970 00:00:00 GMT")
	frappe.local.cookie_manager.set_cookie("system_user", "", expires="Thu, 01 Jan 1970 00:00:00 GMT")

	# Clear cached credentials
	frappe.cache().delete(tmp_id + "_usr")
	frappe.cache().delete(tmp_id + "_pwd")
	frappe.cache().delete(tmp_id + "_otp_secret")

	return success_response(
		message=_("Logged in successfully"),
		data={
			"full_name": user_doc.full_name,
			"email": user,
			"access_token": access_token,
			"refresh_token": refresh_token,
			"token_type": "Bearer",
			"expires_in": 86400,  # 24 hours in seconds
			"permissions": user_permissions,
		}
	)

