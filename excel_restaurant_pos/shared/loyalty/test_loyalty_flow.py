# Copyright (c) 2026, Excel and contributors
# See license.txt

"""End-to-end loyalty flows against real invoices, payments and the ledger."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, cint, flt, now_datetime, nowdate

from excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry import create_payment_entry
from excel_restaurant_pos.shared.loyalty import accounts, earning, events, expiry, holds, ledger, redemption
from excel_restaurant_pos.shared.loyalty.settings import ACCOUNT, TXN

COMPANY = "_Test Company"
ITEM = "_Loyalty Test Item"
ITEM_GROUP = "_Loyalty Test Group"
ZONE = "_Loyalty Test Zone"
PROGRAMME = "_Loyalty Test Programme"
LIABILITY = "_Loyalty Liability - _TC"
EXPENSE = "_Loyalty Expense - _TC"
SETTINGS = "ArcPOS Loyalty Settings"


def ensure(doctype, name, values):
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)
	return name


def setup_fixtures():
	ensure("Account", LIABILITY, {"account_name": "_Loyalty Liability", "parent_account": "Current Liabilities - _TC", "company": COMPANY})
	ensure("Account", EXPENSE, {"account_name": "_Loyalty Expense", "parent_account": "Indirect Expenses - _TC", "company": COMPANY})
	if frappe.db.table_exists("Zone"):
		ensure("Zone", ZONE, {"excel_zone_name": ZONE})
	ensure("Item Group", ITEM_GROUP, {"item_group_name": ITEM_GROUP, "parent_item_group": "All Item Groups"})
	item = {"item_code": ITEM, "item_name": ITEM, "item_group": ITEM_GROUP, "is_stock_item": 0, "stock_uom": "Nos", "description": ITEM}
	# excel_erpnext makes this mandatory on sites that have it.
	if frappe.get_meta("Item").has_field("has_excel_serials"):
		item["has_excel_serials"] = "No"
	ensure("Item", ITEM, item)

	cash = frappe.get_doc("Mode of Payment", "Cash")
	if not any(row.company == COMPANY for row in cash.accounts):
		cash.append("accounts", {"company": COMPANY, "default_account": "Cash - _TC"})
		cash.save(ignore_permissions=True)

	if not frappe.db.exists("ArcPOS Loyalty Programme", PROGRAMME):
		frappe.get_doc(
			{
				"doctype": "ArcPOS Loyalty Programme",
				"programme_name": PROGRAMME,
				"company": COMPANY,
				"status": "Active",
				"start_date": add_days(nowdate(), -30),
				"point_value": 0.1,
				"points_rounding": "Floor",
				"earn_basis": "Net Total (excl. tax)",
				"earn_on": "Paid",
				"pending_days": 0,
				"expiry_mode": "Fixed Days per Lot",
				"expiry_days": 365,
				"min_redeem_points": 10,
				"redeem_increment": 10,
				"max_redeem_percent_of_order": 100,
				"restore_grace_days": 7,
				"base_rules": [{"rule_name": "1 per 1", "rule_type": "Spend Rate", "points": 1, "per_amount": 1}],
			}
		).insert(ignore_permissions=True)

	settings = frappe.get_doc(SETTINGS)
	settings.update(
		{
			"enabled": 1,
			"active_programme": PROGRAMME,
			"auto_enrol_on_signup": 1,
			"auto_enrol_on_first_order": 1,
			"loyalty_mode_of_payment": "Loyalty Points",
			"liability_account": LIABILITY,
			"expense_account": EXPENSE,
			"step_up_threshold_points": 0,
			"adjustment_approval_threshold": 500,
		}
	)
	settings.save(ignore_permissions=True)


def new_customer(label):
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"_Loyalty {label} {frappe.generate_hash(length=6)}",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups",
			"territory": "All Territories",
			"custom_zone": ZONE if frappe.db.table_exists("Zone") else None,
		}
	)
	customer.insert(ignore_permissions=True)
	return customer.name


def make_invoice(customer, qty=2, rate=50, submit=True):
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": COMPANY,
			"customer": customer,
			"posting_date": nowdate(),
			"due_date": nowdate(),
			"currency": "INR",
			"debit_to": "Debtors - _TC",
			"custom_order_from": "Table",
			"custom_service_type": "Dine-in",
			"items": [{"item_code": ITEM, "qty": qty, "rate": rate, "income_account": "Sales - _TC", "cost_center": "Main - _TC"}],
		}
	)
	si.insert(ignore_permissions=True)
	# after_insert hooks write to the invoice, so submit a fresh copy.
	si = frappe.get_doc("Sales Invoice", si.name)
	if submit:
		si.submit()
	return si


def pay(si):
	outstanding = frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")
	return create_payment_entry(si.name, [{"mode_of_payment": "Cash", "amount": flt(outstanding)}])


def balance(account):
	return cint(frappe.db.get_value(ACCOUNT, account, "available_points"))


class TestLoyaltyFlow(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Sales Invoice hooks elsewhere in the app commit mid-save
		# (customer_change_handler); without this the class rollback could not
		# undo these fixtures.
		no_commit = patch.object(frappe.db, "commit", lambda *args, **kwargs: None)
		no_commit.start()
		cls.addClassCleanup(no_commit.stop)
		setup_fixtures()

	def member(self, label="Member"):
		customer = new_customer(label)
		return customer, accounts.enrol(customer, source="Admin")

	def test_paid_order_earns_once(self):
		customer, account = self.member()
		si = make_invoice(customer)
		self.assertFalse(ledger.find_by_key_prefix(f"earn:{si.name}:"), "unpaid orders must not earn")

		pay(si)
		rows = ledger.find_by_key_prefix(f"earn:{si.name}:")
		self.assertEqual(len(rows), 1)
		self.assertEqual(balance(account), 100)

		# Retried hooks do not award again.
		earning.award_for_invoice(si.name)
		earning.on_invoice_submit(frappe.get_doc("Sales Invoice", si.name))
		self.assertEqual(ledger.find_by_key_prefix(f"earn:{si.name}:"), rows)
		self.assertEqual(balance(account), 100)
		self.assertEqual(cint(frappe.db.get_value("Sales Invoice", si.name, "custom_loyalty_points_earned")), 100)

	def test_points_tender_and_cancel_restores(self):
		customer, account = self.member()
		pay(make_invoice(customer))  # 100 points

		si = make_invoice(customer, qty=1, rate=50, submit=False)
		result = redemption.apply_points(si.name, 40)
		self.assertEqual(result["value"], 4.0)
		self.assertEqual(result["amount_due"], 46.0)

		frappe.get_doc("Sales Invoice", si.name).submit()
		self.assertTrue(ledger.find_by_key(f"redeem:{si.name}"))
		self.assertEqual(balance(account), 60)
		loyalty_pe = redemption.loyalty_payment_entries(si.name)
		self.assertEqual(len(loyalty_pe), 1)
		self.assertEqual(flt(frappe.db.get_value("Payment Entry", loyalty_pe[0], "paid_amount")), 4.0)
		self.assertEqual(frappe.db.get_value("Payment Entry", loyalty_pe[0], "paid_to"), LIABILITY)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), 46.0)

		cash = pay(si)
		# The points-paid part earns nothing: 46 of the 50.
		self.assertEqual(balance(account), 106)

		for name in cash:
			frappe.get_doc("Payment Entry", name).cancel()
		frappe.get_doc("Sales Invoice", si.name).cancel()
		self.assertEqual(balance(account), 100)
		self.assertFalse(redemption.loyalty_payment_entries(si.name))

	def test_second_order_cannot_spend_the_same_points(self):
		customer, account = self.member()
		pay(make_invoice(customer))  # 100 points

		first = make_invoice(customer, submit=False)
		second = make_invoice(customer, submit=False)
		redemption.apply_points(first.name, 100)
		redemption.apply_points(second.name, 100)

		frappe.get_doc("Sales Invoice", first.name).submit()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Sales Invoice", second.name).submit()
		self.assertEqual(balance(account), 0)

	def test_credit_note_reverses_pro_rata(self):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		customer, account = self.member()
		si = make_invoice(customer, qty=4, rate=25)
		pay(si)
		self.assertEqual(balance(account), 100)

		credit = make_sales_return(si.name)
		credit.items[0].qty = -1
		credit.insert(ignore_permissions=True)
		frappe.get_doc("Sales Invoice", credit.name).submit()
		self.assertEqual(balance(account), 75)

	def test_excluded_and_disabled_never_earn(self):
		customer, _account = self.member("Excluded")
		settings = frappe.get_doc(SETTINGS)
		settings.append("excluded_customers", {"customer": customer})
		settings.save(ignore_permissions=True)
		try:
			pay(make_invoice(customer))
			self.assertFalse(frappe.db.exists(TXN, {"customer": customer}))
		finally:
			settings.reload()
			settings.set("excluded_customers", [])
			settings.save(ignore_permissions=True)

		other, account = self.member("Disabled")
		frappe.db.set_single_value(SETTINGS, "enabled", 0)
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		try:
			pay(make_invoice(other))
			self.assertFalse(frappe.db.exists(TXN, {"account": account}))
		finally:
			frappe.db.set_single_value(SETTINGS, "enabled", 1)
			frappe.clear_document_cache(SETTINGS, SETTINGS)

	def test_ledger_rows_are_immutable(self):
		customer, account = self.member()
		pay(make_invoice(customer))
		row = frappe.get_doc(TXN, frappe.get_all(TXN, filters={"account": account}, pluck="name")[0])
		row.points = 99999
		with self.assertRaises(frappe.ValidationError):
			row.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(TXN, row.name, ignore_permissions=True, force=True)

	def test_expiry_and_cache(self):
		_customer, account = self.member()
		locked = ledger.lock_account(account)
		lot, _created = ledger.post_credit(locked, "Adjust", 30, f"test-expiry:{account}", expiry_date=add_days(nowdate(), -1))
		self.assertEqual(ledger.recompute_cache(account)["available_points"], 30)

		expiry._expire_lots(account, [lot])
		self.assertEqual(balance(account), 0)
		self.assertEqual(frappe.db.get_value(TXN, lot, "status"), "Expired")
		self.assertIsNone(ledger.expire_lot(account, lot, f"expire:{lot}"))

		frappe.db.set_value(ACCOUNT, account, "available_points", 999)
		values = ledger.compute_balances(account)
		self.assertEqual(values["available_points"], 0)
		self.assertEqual(values["lifetime_expired"], 30)

	def test_adjustment_needs_approval_above_threshold(self):
		from excel_restaurant_pos.excel_restaurant_pos.doctype.arcpos_loyalty_adjustment.arcpos_loyalty_adjustment import (
			approve,
		)

		_customer, account = self.member()
		small = frappe.get_doc(
			{"doctype": "ArcPOS Loyalty Adjustment", "account": account, "points": 50, "reason": "Goodwill", "remarks": "test"}
		)
		small.insert()
		small.submit()
		self.assertEqual(balance(account), 50)

		large = frappe.get_doc(
			{"doctype": "ArcPOS Loyalty Adjustment", "account": account, "points": 1000, "reason": "Goodwill", "remarks": "test"}
		)
		large.insert()
		self.assertTrue(large.requires_approval)
		self.assertEqual(large.approval_status, "Pending Approval")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("ArcPOS Loyalty Adjustment", large.name).submit()
		approve(large.name)
		self.assertEqual(balance(account), 1050)

		frappe.get_doc("ArcPOS Loyalty Adjustment", large.name).cancel()
		self.assertEqual(balance(account), 50)

	def test_reports_on_live_data(self):
		from frappe.desk.query_report import run

		customer, account = self.member("Reports")
		pay(make_invoice(customer))
		si = make_invoice(customer, qty=1, rate=50, submit=False)
		redemption.apply_points(si.name, 20)
		frappe.get_doc("Sales Invoice", si.name).submit()

		def rows(report, **filters):
			return run(report, filters={"programme": PROGRAMME, **filters}, ignore_prepared_report=True)["result"]

		summary = rows("Loyalty Points Summary", group_by="Month")
		self.assertGreaterEqual(sum(r["earned"] for r in summary if isinstance(r, dict)), 100)
		self.assertTrue(rows("Customer Loyalty Balances"))
		self.assertTrue(any(r.get("account") == account for r in rows("Loyalty Redemption Activity")))
		liability = rows("Loyalty Liability")
		self.assertTrue(any(r.get("points") for r in liability))
		for report in ("Loyalty Campaign Performance", "Loyalty Expiry Forecast", "Loyalty Adjustment Audit"):
			rows(report)

	def test_signup_bonus_once(self):
		programme = frappe.get_doc("ArcPOS Loyalty Programme", PROGRAMME)
		programme.append(
			"base_rules",
			{"rule_name": "Welcome", "trigger": "Event", "event_type": "customer_signup", "rule_type": "Fixed Bonus", "points": 5},
		)
		programme.save(ignore_permissions=True)
		try:
			customer, account = self.member("Signup")
			events.emit("customer_signup", customer, reference_doctype="Customer", reference_name=customer)
			events.emit("customer_signup", customer, reference_doctype="Customer", reference_name=customer)
			events.emit("customer_signup", customer, reference_key="another-ref")
			self.assertEqual(balance(account), 5)
		finally:
			programme.reload()
			programme.set("base_rules", [r for r in programme.base_rules if r.trigger != "Event"])
			programme.save(ignore_permissions=True)

	def test_stale_account_stamp_never_earns_for_someone_else(self):
		_customer_a, account_a = self.member("Stale A")
		customer_b, account_b = self.member("Stale B")
		si = make_invoice(customer_b, submit=False)
		# Left over from an earlier customer on the order (points removed,
		# customer changed): validate clears it, and earning ignores it anyway.
		frappe.db.set_value("Sales Invoice", si.name, "custom_loyalty_account", account_a)
		si = frappe.get_doc("Sales Invoice", si.name)
		si.submit()
		pay(si)
		self.assertEqual(balance(account_a), 0)
		self.assertEqual(balance(account_b), 100)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si.name, "custom_loyalty_account"), account_b)

	def test_concurrent_award_keeps_the_stamped_total(self):
		customer, _account = self.member("Race")
		si = make_invoice(customer)
		pay(si)
		# A second award (the submit hook racing the payment hook) is a no-op,
		# and must not overwrite the invoice's earned total with 0.
		earning.award_for_invoice(si.name)
		self.assertEqual(cint(frappe.db.get_value("Sales Invoice", si.name, "custom_loyalty_points_earned")), 100)

	def test_step_up_code_is_bound_to_its_amount(self):
		from excel_restaurant_pos.shared.loyalty import otp

		customer, account = self.member("OTP")
		si = make_invoice(customer, submit=False)
		with patch("excel_restaurant_pos.shared.loyalty.notifications.send_code", return_value="m***@e***.com"), patch(
			"secrets.randbelow", return_value=123456
		):
			result = otp.request(account, si.name, 200)
		self.assertEqual(result["points"], 200)
		with self.assertRaises(frappe.ValidationError):
			otp.verify(account, si.name, "123456", 900)
		self.assertTrue(otp.verify(account, si.name, "123456"))
		self.assertEqual(cint(frappe.cache().get_value(otp._verified_key(account, si.name))), 200)

	def test_reward_replay_key_is_per_member(self):
		from excel_restaurant_pos.shared.loyalty import rewards

		_c1, first = self.member("Reward A")
		_c2, second = self.member("Reward B")
		with patch.object(rewards, "_issue_voucher", side_effect=AssertionError("must not issue")), patch.object(
			ledger, "find_by_key", side_effect=lambda key: "TXN-A" if key == f"reward:{first}:same-id-123" else None
		), patch.object(rewards, "_voucher_result", side_effect=lambda txn: {"transaction": txn}):
			self.assertEqual(rewards.redeem_reward(first, "any", "same-id-123"), {"transaction": "TXN-A"})
			# The other member reusing the id does not get the first member's voucher.
			with self.assertRaises(frappe.DoesNotExistError):
				rewards.redeem_reward(second, "_no_such_reward", "same-id-123")

	def ticket(self, si, paid=False):
		values = {"doctype": "Payment Ticket", "invoice_no": si.name, "ticket": frappe.generate_hash()}
		if paid:
			values["redeemed_at"] = now_datetime()
		frappe.get_doc(values).insert(ignore_permissions=True)

	def test_card_checkout_holds_its_points(self):
		customer, account = self.member("Hold")
		pay(make_invoice(customer))  # 100 points

		online = make_invoice(customer, submit=False)
		redemption.apply_points(online.name, 60)
		holds.hold_for_checkout(frappe.get_doc("Sales Invoice", online.name))
		self.ticket(online)

		# Elsewhere only what the checkout leaves free can be spent.
		counter = make_invoice(customer, submit=False)
		self.assertEqual(redemption.options(frappe.get_doc("Sales Invoice", counter.name))["available_points"], 40)
		with self.assertRaises(frappe.ValidationError):
			redemption.apply_points(counter.name, 60)
		with self.assertRaises(frappe.ValidationError):
			holds.assert_spendable(account, 41)

		# A second checkout cannot take the held points either.
		second = make_invoice(customer, submit=False)
		frappe.db.set_value("Sales Invoice", second.name, {"custom_loyalty_points_redeemed": 60, "custom_loyalty_account": account})
		with self.assertRaises(frappe.ValidationError):
			holds.hold_for_checkout(frappe.get_doc("Sales Invoice", second.name))

		frappe.get_doc("Sales Invoice", online.name).submit()
		self.assertEqual(ledger.available_balance(account), 40)

	def test_paid_checkout_submits_even_when_points_are_gone(self):
		customer, account = self.member("Paid")
		pay(make_invoice(customer))  # 100 points

		online = make_invoice(customer, submit=False)
		redemption.apply_points(online.name, 60)
		self.ticket(online, paid=True)
		# An adjustment (or expiry) does not wait for holds.
		ledger.post_debit(ledger.lock_account(account), "Adjust", 70, f"test-drain:{online.name}")

		frappe.get_doc("Sales Invoice", online.name).submit()
		debit = ledger.find_by_key(f"redeem:{online.name}")
		self.assertEqual(cint(frappe.db.get_value(TXN, debit, "outstanding_debt")), 30)
		self.assertEqual(ledger.available_balance(account), -30)

		# Cancelling gives back what was taken and forgives the rest.
		frappe.get_doc("Sales Invoice", online.name).cancel()
		self.assertEqual(cint(frappe.db.get_value(TXN, debit, "outstanding_debt")), 0)
		self.assertEqual(ledger.available_balance(account), 30)

	def test_step_up_counters_are_atomic(self):
		from excel_restaurant_pos.shared.loyalty import otp

		customer, account = self.member("OTP limits")
		si = make_invoice(customer, submit=False)
		with patch("excel_restaurant_pos.shared.loyalty.notifications.send_code", return_value="x"), patch(
			"secrets.randbelow", return_value=123456
		):
			for _ in range(otp.MAX_SENDS):
				otp.request(account, si.name, 200)
			with self.assertRaises(frappe.ValidationError):
				otp.request(account, si.name, 200)
		for _ in range(otp.MAX_ATTEMPTS):
			self.assertFalse(otp.verify(account, si.name, "000000"))
		with self.assertRaises(frappe.ValidationError):
			otp.verify(account, si.name, "123456")
		frappe.cache().delete_value([f"loyalty:otp-sends:{account}", otp._tries_key(account, si.name)])

	def test_long_keys_fit_the_column(self):
		key = "event:custom_event:" + "x" * 300
		short = ledger.norm_key(key)
		self.assertLessEqual(len(short), ledger.KEY_LENGTH)
		self.assertTrue(short.startswith("event:custom_event:"))
		self.assertNotEqual(short, ledger.norm_key(key + "y"))
