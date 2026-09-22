"""The push notification that rings the staff app's new-order alarm.

Alarm display and audio are owned by the native Android layer
(``OrderAlarmService`` via ``ArcPosMessagingService``).  The backend must
deliver a **high-priority data-only** message so that ``onMessageReceived``
is called while the app is backgrounded or killed.

Android constraint: if the Expo/FCM message contains a root ``title``,
``body``, or ``sound`` the OS intercepts it and shows a tray notification
without calling ``onMessageReceived`` — the native alarm path never starts.

The mobile app plays its alarm for a message whose ``data.type`` is
ORDER_ALARM.  The ``title`` and ``message`` are carried inside ``data`` only;
the alarm screen reads them from there.
"""

ORDER_ALARM_CHANNEL = "arcpos_order_alarm_v2"
ORDER_ALARM_TYPE = "ORDER_ALARM"
# What the staff app routes on. Not the doctype -- orders are Sales Invoices.
ORDER_ALARM_DOCUMENT_TYPE = "Restaurant Order"

# Statuses in which an order is arriving for staff: a table order just opened,
# a website order waiting, or one sent to the kitchen or scheduled. Any other
# status is a change to an order staff already have.
NEW_ORDER_STATUSES = ("Open", "Waiting", "In kitchen", "Scheduled")


def order_alarm_title(document_name, status=None):
	if not status or status in NEW_ORDER_STATUSES:
		return f"New Order #{document_name}"
	return f"Order #{document_name} {status}"


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
	"""A high-priority data-only Expo PushMessage that triggers the native alarm.

	No root title/body/sound/channelId — those would make Android intercept the
	message as a display notification and skip onMessageReceived, preventing
	OrderAlarmService from starting while the app is backgrounded.
	"""
	from exponent_server_sdk import PushMessage

	title = title or order_alarm_title(document_name)
	return PushMessage(
		to=token,
		priority="high",
		# No title / body / sound / channel_id / display_in_foreground at root.
		# Android FCM delivers data-only messages to onMessageReceived regardless
		# of app state (foreground / background / killed).
		data={
			**(extra_data or {}),
			"is_alarm": "true",
			"type": ORDER_ALARM_TYPE,
			"document_name": document_name,
			"document_type": ORDER_ALARM_DOCUMENT_TYPE,
			"title": title,
			"message": message,
		},
	)
