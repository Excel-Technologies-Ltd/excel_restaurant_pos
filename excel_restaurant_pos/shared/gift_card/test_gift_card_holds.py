# Copyright (c) 2026, Excel and contributors
# See license.txt

"""Gift card amounts held by a card checkout, and paid orders that must submit."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime, nowdate

from excel_restaurant_pos.shared.gift_card import holds, services
from excel_restaurant_pos.shared.gift_card.validation import GIFT_CARD_TYPE
from excel_restaurant_pos.shared.loyalty.test_loyalty_flow import make_invoice, new_customer, setup_fixtures


def gift_card(face=100, redeemed=()):
	name = f"_GC-{frappe.generate_hash(length=8).upper()}"
	frappe.get_doc(
		{
			"doctype": "Coupon Code",
			"name": name,
			"coupon_name": name,
			"coupon_code": name,
			"coupon_type": GIFT_CARD_TYPE,
			"custom_status": "Active",
			"custom_discount_amount": face,
			"custom_available_balance": face - sum(amount for _invoice, amount in redeemed),
		}
	).db_insert()
	for idx, (invoice, amount) in enumerate(redeemed, start=1):
		redemption(name, invoice, amount, idx)
	return name


def redemption(card, invoice, amount, idx):
	frappe.get_doc(
		{
			"doctype": holds.REDEEMED_DOCTYPE,
			"parent": card,
			"parenttype": "Coupon Code",
			"parentfield": holds.REDEEMED_FIELD,
			"idx": idx,
			"sales_invoice": invoice,
			"redeemed_amount": amount,
		}
	).db_insert()


def draft_with_card(customer, card, amount, ticket=False, paid=False):
	si = make_invoice(customer, submit=False)
	frappe.get_doc(
		{
			"doctype": holds.APPLIED_DOCTYPE,
			"parent": si.name,
			"parenttype": "Sales Invoice",
			"parentfield": holds.APPLIED_FIELD,
			"idx": 1,
			"gift_card_code": card,
			"redeemed_amount": amount,
		}
	).db_insert()
	if ticket or paid:
		values = {"doctype": "Payment Ticket", "invoice_no": si.name, "ticket": frappe.generate_hash()}
		if paid:
			values["redeemed_at"] = now_datetime()
		frappe.get_doc(values).insert(ignore_permissions=True)
	return frappe.get_doc("Sales Invoice", si.name)


class TestGiftCardHolds(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		no_commit = patch.object(frappe.db, "commit", lambda *args, **kwargs: None)
		no_commit.start()
		cls.addClassCleanup(no_commit.stop)
		setup_fixtures()
		cls.customer = new_customer("Gift card")

	def test_checkout_holds_its_amount(self):
		card = gift_card(100)
		online = draft_with_card(self.customer, card, 60, ticket=True)
		self.assertEqual(holds.held_amount(card), 60)
		self.assertEqual(holds.held_amount(card, exclude_invoice=online.name), 0)
		holds.hold_for_checkout(online)

		# Another checkout can only take what is left.
		greedy = draft_with_card(self.customer, card, 60)
		with self.assertRaises(frappe.ValidationError):
			holds.hold_for_checkout(greedy)
		holds.hold_for_checkout(draft_with_card(self.customer, card, 40))

		# And so does the balance every other order sees.
		from excel_restaurant_pos.shared.gift_card.redemption import _assert_gift_card_redeemable_balance

		coupon = frappe.get_doc("Coupon Code", card)
		self.assertEqual(_assert_gift_card_redeemable_balance(coupon, nowdate(), exclude_invoice=greedy.name), 40)

	def test_drafts_without_a_ticket_hold_nothing(self):
		card = gift_card(100)
		draft_with_card(self.customer, card, 60)
		self.assertEqual(holds.held_amount(card), 0)

	def test_unpaid_order_cannot_overdraw(self):
		card = gift_card(100, redeemed=[("ORD-ELSEWHERE", 80)])
		order = draft_with_card(self.customer, card, 50, ticket=True)
		with patch.object(services, "is_gift_card_redemption_channel_allowed", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				services.record_gift_card_redemptions(order)

	def test_paid_order_submits_and_keeps_other_redemptions(self):
		card = gift_card(100, redeemed=[("ORD-ELSEWHERE", 80)])
		order = draft_with_card(self.customer, card, 50, paid=True)
		with patch.object(services, "is_gift_card_redemption_channel_allowed", return_value=True), patch.object(
			frappe, "log_error"
		) as log_error:
			services.record_gift_card_redemptions(order)
			# A retried hook does not spend twice.
			services.record_gift_card_redemptions(order)
		log_error.assert_called()

		rows = frappe.get_all(
			holds.REDEEMED_DOCTYPE, filters={"parent": card}, fields=["sales_invoice", "redeemed_amount"], order_by="idx"
		)
		self.assertEqual([(r.sales_invoice, flt(r.redeemed_amount)) for r in rows], [("ORD-ELSEWHERE", 80), (order.name, 50)])
		balance, status = frappe.db.get_value("Coupon Code", card, ["custom_available_balance", "custom_status"])
		self.assertEqual(flt(balance), 0)
		self.assertEqual(status, "Used")
