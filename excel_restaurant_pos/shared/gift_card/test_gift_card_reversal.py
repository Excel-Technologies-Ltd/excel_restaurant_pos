# Copyright (c) 2026, Excel and contributors
# See license.txt

"""Gift cards given back by cancelled and returned orders."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from excel_restaurant_pos.shared.gift_card import reversal
from excel_restaurant_pos.shared.gift_card.test_gift_card_holds import draft_with_card, gift_card
from excel_restaurant_pos.shared.loyalty.test_loyalty_flow import make_invoice, new_customer, setup_fixtures

CHANNEL_CHECKS = (
	"excel_restaurant_pos.shared.gift_card.services.is_gift_card_redemption_channel_allowed",
	"excel_restaurant_pos.shared.gift_card.redemption.is_gift_card_redemption_channel_allowed",
)


def card_state(code):
	balance, status = frappe.db.get_value("Coupon Code", code, ["custom_available_balance", "custom_status"])
	return flt(balance), status


class TestGiftCardReversal(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		no_commit = patch.object(frappe.db, "commit", lambda *args, **kwargs: None)
		no_commit.start()
		cls.addClassCleanup(no_commit.stop)
		for target in CHANNEL_CHECKS:
			allowed = patch(target, return_value=True)
			allowed.start()
			cls.addClassCleanup(allowed.stop)
		setup_fixtures()
		cls.customer = new_customer("Gift card reversal")

	def spend(self, card, amount):
		order = draft_with_card(self.customer, card, amount)
		order.submit()
		return order

	def test_cancel_gives_the_card_back(self):
		card = gift_card(100)
		order = self.spend(card, 100)
		self.assertEqual(card_state(card), (0, "Used"))

		frappe.get_doc("Sales Invoice", order.name).cancel()
		self.assertEqual(card_state(card), (100, "Active"))

	def test_returns_give_back_the_discount_once(self):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		card = gift_card(100)
		order = self.spend(card, 60)
		self.assertEqual(card_state(card)[0], 40)

		first = make_sales_return(order.name)
		first.items[0].qty = -1
		first.insert(ignore_permissions=True)
		frappe.get_doc("Sales Invoice", first.name).submit()  # after_insert hooks write to it
		# The credit note carries the whole 60 discount, so the card gets it all back.
		self.assertEqual(card_state(card)[0], 100)

		second = make_sales_return(order.name)
		second.insert(ignore_permissions=True)
		frappe.get_doc("Sales Invoice", second.name).submit()
		self.assertEqual(card_state(card)[0], 100)

		# Cancelling a credit note takes back what it gave.
		frappe.get_doc("Sales Invoice", first.name).cancel()
		self.assertEqual(card_state(card)[0], 40)

	def test_an_unused_card_whose_sale_is_returned_is_rejected(self):
		unused, spent = gift_card(25), gift_card(25, redeemed=[("ORD-ELSEWHERE", 5)])
		sale = make_invoice(self.customer)
		for code in (unused, spent):
			frappe.db.set_value("Coupon Code", code, "custom_generated_on_order", sale.name)
		credit = frappe._dict(
			name="CREDIT-TEST",
			is_return=1,
			return_against=sale.name,
			items=[
				frappe._dict(custom_is_gift_card_item=1, custom_gift_card_type="Existing", custom_gift_card_code=unused, qty=-1),
				frappe._dict(custom_is_gift_card_item=1, custom_gift_card_type="Existing", custom_gift_card_code=spent, qty=-1),
			],
		)
		with patch.object(frappe, "log_error") as log_error:
			reversal._reject_returned_sales(credit)
		self.assertEqual(card_state(unused)[1], "Rejected")
		self.assertEqual(card_state(spent)[1], "Active")
		log_error.assert_called_once()
