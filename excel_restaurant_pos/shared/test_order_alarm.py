# Copyright (c) 2026, Excel and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from excel_restaurant_pos.shared.order_alarm import order_alarm_message, order_alarm_push

TOKEN = "ExponentPushToken[xxxxxxxxxxxxxx]"


class TestOrderAlarm(FrappeTestCase):
	def test_the_payload_is_the_agreed_shape(self):
		payload = order_alarm_push(TOKEN, "ACC-SINV-2026-0001", "Table 5 placed an order").get_payload()

		self.assertEqual(payload["to"], TOKEN)
		self.assertEqual(payload["priority"], "high")
		self.assertEqual(payload["channelId"], "arcpos_order_alarm_v2")
		self.assertIs(payload["_displayInForeground"], True)
		self.assertEqual(payload["data"], {
			"is_alarm": True,
			"type": "ORDER_ALARM",
			"document_name": "ACC-SINV-2026-0001",
			"document_type": "Restaurant Order",
			"title": "New Order #ACC-SINV-2026-0001",
			"message": "Table 5 placed an order",
		})
		# Also shown by app builds that do not know the alarm yet.
		self.assertEqual(payload["title"], "New Order #ACC-SINV-2026-0001")
		self.assertEqual(payload["body"], "Table 5 placed an order")

	def test_extra_data_never_overrides_the_alarm_fields(self):
		payload = order_alarm_push(TOKEN, "X", "m", extra_data={"type": "other", "order_id": "u-1"}).get_payload()
		self.assertEqual(payload["data"]["type"], "ORDER_ALARM")
		self.assertEqual(payload["data"]["order_id"], "u-1")

	def test_the_message_names_the_table_or_the_customer(self):
		self.assertEqual(order_alarm_message(frappe._dict(custom_linked_table="Table 5")), "Table 5 placed an order")
		self.assertEqual(
			order_alarm_message(frappe._dict(custom_customer_full_name="Anamul Haque", custom_service_type="Pickup")),
			"Pickup order from Anamul Haque",
		)
		self.assertEqual(order_alarm_message(frappe._dict()), "A new order was placed")


class TestRulesTickedRingAsAlarm(FrappeTestCase):
	"""send_notification_to_role against real users and tokens, Expo mocked."""

	ROLE, USER = "_Test Alarm Role", "alarm.waiter@example.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", cls.ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": cls.ROLE}).insert(ignore_permissions=True)
		user = frappe.get_doc({"doctype": "User", "email": cls.USER, "first_name": "Alarm"})
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)
		user.add_roles(cls.ROLE)
		frappe.get_doc({
			"doctype": "ArcPOS Notification Token", "user": cls.USER,
			"token_list": [{"token": TOKEN}],
		}).insert(ignore_permissions=True)

	def sent(self, rule, name):
		from unittest.mock import MagicMock, patch

		import importlib

		# The package __init__ re-exports a function under the module's name.
		module = importlib.import_module("excel_restaurant_pos.doc_event.sales_invoice.on_update_sales_invoice")

		doc = frappe._dict(name=name, customer="C", custom_customer_full_name="Anamul Haque",
		                   custom_service_type="Pickup", custom_order_status="In kitchen", grand_total=0, currency="CAD")
		client = MagicMock()
		client.publish_multiple.side_effect = lambda chunk: [MagicMock() for _ in chunk]
		with patch("exponent_server_sdk.PushClient", return_value=client), \
		     patch(f"{module.__name__}.frappe.publish_realtime"):
			module.send_notification_to_role(doc, {"if_role": self.ROLE, **rule})
		return [m.get_payload() for call in client.publish_multiple.call_args_list for m in call.args[0]]

	def test_a_ticked_rule_rings_the_alarm(self):
		(payload,) = self.sent({"ring_as_alarm": 1}, "WEB-TEST-ALARM")
		self.assertEqual(payload["channelId"], "arcpos_order_alarm_v2")
		self.assertEqual(payload["data"]["type"], "ORDER_ALARM")
		self.assertEqual(payload["data"]["message"], "Pickup order from Anamul Haque")

	def test_an_unticked_rule_is_unchanged(self):
		(payload,) = self.sent({"ring_as_alarm": 0}, "WEB-TEST-PLAIN")
		self.assertNotIn("channelId", payload)
		self.assertEqual(payload["data"]["document_type"], "Sales Invoice")
