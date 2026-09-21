"""The push notification that rings the staff app's new-order alarm.

The mobile app plays its alarm for a message on the `arcpos_order_alarm_v2`
Android channel whose `data.type` is ORDER_ALARM. The title and message are
sent twice: at the top level, so an app build that does not know the alarm yet
still shows an ordinary notification, and inside `data`, which is what the
alarm screen reads.
"""

ORDER_ALARM_CHANNEL = "arcpos_order_alarm_v2"
ORDER_ALARM_TYPE = "ORDER_ALARM"
# What the staff app routes on. Not the doctype -- orders are Sales Invoices.
ORDER_ALARM_DOCUMENT_TYPE = "Restaurant Order"


def order_alarm_title(document_name):
	return f"New Order #{document_name}"


def order_alarm_message(doc):
	"""One line saying who ordered: the table, or the customer and service."""
	table = doc.get("custom_linked_table")
	if table:
		return f"{table} placed an order"

	who = doc.get("custom_customer_full_name") or doc.get("customer_name") or doc.get("customer")
	service = doc.get("custom_service_type")
	if who and service:
		return f"{service} order from {who}"
	if who:
		return f"{who} placed an order"
	return "A new order was placed"


def order_alarm_push(token, document_name, message, title=None, extra_data=None):
	"""An Expo PushMessage in the alarm format."""
	from exponent_server_sdk import PushMessage

	title = title or order_alarm_title(document_name)
	return PushMessage(
		to=token,
		title=title,
		body=message,
		sound="default",
		priority="high",
		channel_id=ORDER_ALARM_CHANNEL,
		display_in_foreground=True,
		data={
			**(extra_data or {}),
			"is_alarm": True,
			"type": ORDER_ALARM_TYPE,
			"document_name": document_name,
			"document_type": ORDER_ALARM_DOCUMENT_TYPE,
			"title": title,
			"message": message,
		},
	)
