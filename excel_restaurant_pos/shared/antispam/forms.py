"""The public forms the bot checks guard, and what each tells a refused caller.

Every guard refuses a form with the same bland message, whichever guard fired:
which one it was is not the caller's business.
"""

from frappe import _

CHECKOUT, SIGNUP, LOGIN = "checkout", "signup", "login"


def refusal_message(form):
	return {
		CHECKOUT: _("This order could not be placed. Please try again."),
		SIGNUP: _("We could not create your account. Please try again."),
		LOGIN: _("We could not sign you in. Please try again."),
	}[form]


def log_title(form, guard):
	label = {CHECKOUT: "Order", SIGNUP: "Sign-up", LOGIN: "Login"}[form]
	return f"{label} rejected: {guard}"
