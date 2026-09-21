"""Which Item Price rows are in force on a given day.

An Item Price carries a validity window -- valid_from .. valid_upto, either end
open. The price readers only ever checked valid_upto, so a price scheduled to
start next week was shown, and charged, from the moment it was entered: set an
offer to begin on Monday and the storefront sold at it all week before.

Every reader goes through here now -- the item list, the item detail popup, add-on
prices and the Meta catalog feed -- and the checkout-side price check will too, so
the menu and the checkout can never disagree about which price is live.
"""

from frappe.utils import getdate, today

# Add these to any Item Price query whose rows are passed to is_live().
VALIDITY_FIELDS = ["valid_from", "valid_upto"]


def is_live(price, on_date=None):
	"""True if `price` is in force on `on_date` (default: today).

	Both ends are inclusive: a price starting today is live today, and so is one
	ending today.
	"""
	on_date = getdate(on_date or today())

	valid_from = price.get("valid_from")
	if valid_from and getdate(valid_from) > on_date:
		return False

	valid_upto = price.get("valid_upto")
	if valid_upto and getdate(valid_upto) < on_date:
		return False

	return True


def live_prices(prices, on_date=None):
	"""The rows of `prices` in force on `on_date` (default: today)."""
	on_date = getdate(on_date or today())
	return [price for price in prices if is_live(price, on_date)]
