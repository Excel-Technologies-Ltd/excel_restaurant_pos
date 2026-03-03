from excel_restaurant_pos.api.payments.helper.check_receipt import check_receipt
import frappe
from frappe.utils import now_datetime
from datetime import timedelta
from excel_restaurant_pos.doc_event.sales_invoice.handlers.create_payment_entry import (
    create_payment_entry,
)


def delete_marked_invoices():
    """
    Delete Sales Invoices that are marked as deleted.
    Runs daily at midnight.

    Condition: docstatus = 0 (Draft) AND custom_is_deleted = 1
    """
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 0,
            "custom_is_deleted": 1,
        },
        pluck="name",
    )

    for invoice_name in invoices:
        try:
            frappe.delete_doc("Sales Invoice", invoice_name, force=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(
                message=f"Failed to delete Sales Invoice {invoice_name}: {str(e)}",
                title="Scheduled Invoice Deletion Error",
            )

    if invoices:
        frappe.logger().info(
            f"Deleted {len(invoices)} marked-as-deleted draft invoices"
        )


def _delete_sales_invoice(invoice_name):
    try:
        frappe.delete_doc("Sales Invoice", invoice_name, force=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            message=f"Failed to delete Sales Invoice {invoice_name}: {str(e)}",
            title="Scheduled Invoice Deletion Error",
        )
    return True


def delete_stale_website_orders():
    """
    Delete stale website orders that have been in draft status for more than 20 minutes.
    Runs every 20 minutes.

    Condition: custom_order_from = "Website" AND docstatus = 0 (Draft) AND creation > 20 minutes ago
    """
    cutoff_time = now_datetime() - timedelta(minutes=20)

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 0,
            "custom_order_from": "Website",
            "creation": ["<", cutoff_time],
        },
        pluck="name",
    )

    for invoice_name in invoices:
        # if payment is done create payment entry manually
        try:
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
        except Exception as e:
            frappe.log_error(
                message=f"Failed to get Sales Invoice {invoice_name}: {str(e)}",
                title="Scheduled Website Order Deletion Error",
            )
            continue

        # get payment ticket (get first record matching invoice_no)
        payment_ticket = None
        try:
            payment_ticket_names = frappe.get_all(
                "Payment Ticket",
                filters={"invoice_no": invoice_name},
                limit=1,
                pluck="name",
            )
            if payment_ticket_names:
                payment_ticket = frappe.get_doc(
                    "Payment Ticket", payment_ticket_names[0]
                )
        except Exception as e:
            frappe.log_error(
                message=f"Failed to get Payment Ticket for invoice {invoice_name}: {str(e)}",
                title="Scheduled Website Order Deletion Error",
            )

        if not payment_ticket:
            _delete_sales_invoice(invoice_name)
            continue

        # check receipt status info
        receipt_status = check_receipt(payment_ticket.ticket)

        # define required values for validation
        receipt_result = receipt_status.get("receipt", {}).get("result", "")
        success_result = receipt_status.get("success", "false")

        # check payment is successful and the receipt is approved
        if success_result != "true" or receipt_result != "a":
            _delete_sales_invoice(invoice_name)
            continue

        # validate order number
        order_number = receipt_status.get("request", {}).get("order_no")
        if order_number != invoice.name:
            _delete_sales_invoice(invoice_name)
            continue

        # submit sales invoice
        try:
            invoice.docstatus = 1
            invoice.save(ignore_permissions=True)

            # get mode of payment configured for website (get first record)
            filters = {"custom_default_website": 1}
            mode_of_payment_names = frappe.get_all(
                "Mode of Payment", filters=filters, limit=1, pluck="mode_of_payment"
            )
            mode_of_payment = (
                mode_of_payment_names[0] if len(mode_of_payment_names) > 0 else None
            )

            # if mode of payment is no configured
            if not mode_of_payment:
                msg = "No mode of payment configured for website"
                frappe.log_error("No Mode Of payment", msg)

            # create payment entry manually
            payments = [
                {
                    "mode_of_payment": mode_of_payment or "Cash",
                    "amount": invoice.grand_total,
                }
            ]

            # enqueue payment entry creation
            args = {"sales_invoice": invoice.name, "payments": payments}
            create_payment_entry(**args)

        except Exception as e:
            frappe.log_error(
                message=f"Failed to delete stale website order {invoice_name}: {str(e)}",
                title="Scheduled Website Order Deletion Error",
            )

    if invoices:
        frappe.logger().info(
            f"Deleted {len(invoices)} stale website orders older than 20 minutes"
        )


def check_scheduled_order_notifications():
    """
    Check for scheduled pickup/delivery orders and send notifications
    30 minutes before the delivery time to Restaurant Chef and Restaurant Manager.
    Runs every 5 minutes.

    Conditions:
    - Service Type: Pickup OR Delivery
    - Order Status: Open, Accepted, Waiting, In kitchen, Preparing, Scheduled,
                    Ready to Deliver, Ready to Pickup, Handover to Delivery
    - Order Schedule Type: Scheduled Later
    - DeliveryDate: Current Date
    - Current Time: 30 minutes before DeliveryTime (within 5-minute window)
    """
    from frappe.utils import (
        now_datetime,
        get_datetime,
        add_to_date,
        getdate,
    )

    # Get current datetime
    current_datetime = now_datetime()
    current_date = getdate(current_datetime)

    # Calculate the target time range (30 minutes from now, with 5-minute window)
    target_time_start = add_to_date(current_datetime, minutes=28)
    target_time_end = add_to_date(current_datetime, minutes=32)

    # Define allowed statuses
    allowed_statuses = [
        "Open",
        "Accepted",
        "Waiting",
        "In kitchen",
        "Preparing",
        "Scheduled",
        "Ready to Deliver",
        "Ready to Pickup",
        "Handover to Delivery",
    ]

    # Define allowed service types
    allowed_service_types = ["Pickup", "Delivery"]

    # Query Sales Invoices matching criteria (both draft and submitted)
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "custom_service_type": ["in", allowed_service_types],
            "custom_order_status": ["in", allowed_statuses],
            "custom_order_schedule_type": "Scheduled Later",
            "custom_delivery_date": current_date,
        },
        fields=[
            "name",
            "custom_delivery_time",
            "custom_service_type",
            "custom_order_status",
            "custom_delivery_date",
            "customer",
            "customer_name",
            "grand_total",
        ],
    )

    if not invoices:
        frappe.logger().debug("No scheduled delivery/pickup orders found for today")
        return

    # Filter invoices within the 30-minute notification window
    notifications_sent = 0
    for invoice in invoices:
        try:
            # Check if delivery_time exists
            if not invoice.custom_delivery_time:
                continue

            # Combine delivery date and time
            delivery_datetime = get_datetime(
                f"{invoice.custom_delivery_date} {invoice.custom_delivery_time}"
            )

            # Check if delivery time falls within the notification window
            if target_time_start <= delivery_datetime <= target_time_end:
                # Check if notification was already sent (cache key with 2-hour TTL)
                cache_key = f"scheduled_order_notification_30min_{invoice.name}"
                if frappe.cache().get_value(cache_key):
                    frappe.logger().debug(
                        f"30-min notification already sent for {invoice.name}, skipping"
                    )
                    continue

                # Send notification to Restaurant Chef and Restaurant Manager
                success = send_scheduled_order_notification_to_staff(invoice)

                if success:
                    # Mark as notified (2-hour cache to prevent duplicate notifications)
                    frappe.cache().set_value(cache_key, True, expires_in_sec=7200)
                    notifications_sent += 1
                    frappe.logger().info(
                        f"Sent 30-min notification for scheduled order: {invoice.name} "
                        f"(Delivery time: {invoice.custom_delivery_time})"
                    )

        except Exception as e:
            frappe.log_error(
                message=f"Error processing 30-min notification for {invoice.name}: {str(e)}",
                title="Scheduled Order 30-Min Notification Error",
            )
            continue

    if notifications_sent > 0:
        frappe.logger().info(
            f"Sent {notifications_sent} scheduled order 30-minute notifications"
        )


def send_scheduled_order_notification_to_staff(invoice):
    """
    Send system and push notifications to Restaurant Chef and Restaurant Manager
    for a scheduled order 30 minutes before delivery/pickup.

    Args:
        invoice: Sales Invoice document dict with fields

    Returns:
        bool: True if notification was sent successfully
    """
    try:
        from exponent_server_sdk import (
            DeviceNotRegisteredError,
            PushClient,
            PushMessage,
            PushServerError,
            PushTicketError,
        )

        has_expo = True
    except ImportError:
        has_expo = False
        frappe.logger().warning(
            "Expo Server SDK not installed, skipping push notifications"
        )

    # Get the full document
    doc = frappe.get_doc("Sales Invoice", invoice.name)

    # Get ArcPOS Settings for email template
    settings = frappe.get_single("ArcPOS Settings")

    # Define target roles for staff notifications
    target_roles = ["Restaurant Chef", "Restaurant Manager"]

    # Prepare notification content
    service_type = doc.custom_service_type or "Delivery/Pickup"
    delivery_time = doc.custom_delivery_time
    customer_name = doc.customer_name or doc.customer

    title = f"Scheduled {service_type} - 30 Minutes Reminder"
    body = (
        f"Order {doc.name} for {customer_name} is scheduled for "
        f"{service_type.lower()} at {delivery_time}. "
        f"Please prepare the order."
    )

    # Send notifications to each role
    notifications_sent = False
    for role in target_roles:
        try:
            # Find all users with the specified role
            users = frappe.db.sql(
                """
                SELECT DISTINCT parent as user
                FROM `tabHas Role`
                WHERE role = %(role)s
                AND parent NOT IN ('Administrator', 'Guest')
                """,
                {"role": role},
                as_dict=True,
            )

            if not users:
                frappe.logger().warning(f"No users found with role: {role}")
                continue

            user_emails = [user.user for user in users]
            frappe.logger().info(
                f"Sending 30-min reminder to {len(user_emails)} users with role {role}"
            )

            # Send email notifications to all users
            if settings.scheduled_order_reminder_template:
                try:
                    email_template = frappe.get_doc(
                        "Email Template", settings.scheduled_order_reminder_template
                    )

                    for user_email in user_emails:
                        try:
                            # Get user full name
                            user_doc = frappe.get_doc("User", user_email)
                            user_full_name = user_doc.full_name or user_email

                            # Prepare template context
                            template_args = {
                                "user_name": user_full_name,
                                "order_name": doc.name,
                                "customer_name": customer_name,
                                "service_type": service_type,
                                "delivery_date": frappe.utils.format_date(
                                    doc.custom_delivery_date, "dd MMM yyyy"
                                ),
                                "delivery_time": frappe.utils.format_time(
                                    delivery_time
                                ),
                                "order_status": doc.custom_order_status or "Scheduled",
                                "grand_total": frappe.utils.fmt_money(
                                    doc.grand_total, currency=doc.currency
                                ),
                                "items": doc.items,
                                "doc": doc,
                            }

                            # Render email template
                            subject = frappe.render_template(
                                email_template.subject, template_args
                            )
                            message = frappe.render_template(
                                email_template.response_html or email_template.response,
                                template_args,
                            )

                            # Send email
                            frappe.sendmail(
                                recipients=[user_email],
                                subject=subject,
                                message=message,
                                now=True,
                            )

                            frappe.logger().info(
                                f"Email notification sent to: {user_email}"
                            )
                            notifications_sent = True

                        except Exception as e:
                            frappe.log_error(
                                f"Error sending email to {user_email}: {str(e)}",
                                "Scheduled Order Notification - Email Error",
                            )

                except Exception as e:
                    frappe.log_error(
                        message=f"Error processing email template for role {role}: {str(e)}",
                        title="Scheduled Order Notification - Email Template Error",
                    )
            else:
                frappe.logger().warning(
                    f"No email template configured in ArcPOS Settings (scheduled_order_reminder_template) for role {role}"
                )

            # Send system notifications to all users
            for user_email in user_emails:
                try:
                    # Check if notification already exists to prevent duplicates
                    from frappe.utils import add_to_date

                    thirty_seconds_ago = add_to_date(now_datetime(), seconds=-30)
                    existing_notification = frappe.db.exists(
                        "Notification Log",
                        {
                            "for_user": user_email,
                            "document_type": "Sales Invoice",
                            "document_name": doc.name,
                            "subject": title,
                            "creation": [">=", thirty_seconds_ago],
                        },
                    )

                    if existing_notification:
                        continue

                    notification = frappe.get_doc(
                        {
                            "doctype": "Notification Log",
                            "for_user": user_email,
                            "from_user": "Administrator",
                            "subject": title,
                            "email_content": body,
                            "document_type": "Sales Invoice",
                            "document_name": doc.name,
                            "type": "Alert",
                            "read": 0,
                        }
                    )
                    notification.insert(ignore_permissions=True)

                    # Publish realtime event
                    frappe.publish_realtime(
                        "sales_invoice_notification_" + user_email,
                        data={
                            "title": title,
                            "body": body,
                            "document_type": "Sales Invoice",
                            "document_name": doc.name,
                        },
                    )
                    notifications_sent = True
                    frappe.logger().info(f"System notification sent to: {user_email}")

                except Exception as e:
                    frappe.log_error(
                        message=f"Error sending system notification to {user_email}: {str(e)}",
                        title="Scheduled Order Notification - System Error",
                    )

            # Send push notifications if Expo is available
            if has_expo:
                try:
                    # Get Expo tokens for users
                    token_docs = frappe.get_all(
                        "ArcPOS Notification Token",
                        filters={"user": ["in", user_emails]},
                        fields=["name", "user"],
                    )

                    if token_docs:
                        push_messages = []
                        for token_doc_name in [t.name for t in token_docs]:
                            token_doc = frappe.get_doc(
                                "ArcPOS Notification Token", token_doc_name
                            )

                            # Get tokens from child table
                            if token_doc.token_list:
                                for token_row in token_doc.token_list:
                                    if (
                                        token_row.token
                                        and PushClient.is_exponent_push_token(
                                            token_row.token
                                        )
                                    ):
                                        push_messages.append(
                                            PushMessage(
                                                to=token_row.token,
                                                title=title,
                                                body=body,
                                                data={
                                                    "document_type": "Sales Invoice",
                                                    "document_name": doc.name,
                                                    "notification_type": "scheduled_30min_reminder",
                                                    "order_status": doc.custom_order_status
                                                    or "",
                                                    "service_type": doc.custom_service_type
                                                    or "",
                                                    "delivery_time": str(
                                                        doc.custom_delivery_time
                                                    ),
                                                },
                                                sound="default",
                                                priority="high",
                                            )
                                        )

                        # Send push notifications in chunks
                        if push_messages:
                            push_client = PushClient()
                            chunk_size = 100
                            for i in range(0, len(push_messages), chunk_size):
                                chunk = push_messages[i : i + chunk_size]
                                try:
                                    responses = push_client.publish_multiple(chunk)
                                    for response in responses:
                                        try:
                                            response.validate_response()
                                        except DeviceNotRegisteredError:
                                            pass  # Token expired, ignore
                                        except (
                                            PushTicketError,
                                            PushServerError,
                                        ) as exc:
                                            frappe.logger().warning(
                                                f"Push notification error: {exc.message}"
                                            )
                                except Exception as e:
                                    frappe.log_error(
                                        message=f"Error sending push notification chunk: {str(e)}",
                                        title="Scheduled Order Notification - Push Error",
                                    )

                            frappe.logger().info(
                                f"Push notifications sent to role: {role}"
                            )

                except Exception as e:
                    frappe.log_error(
                        message=f"Error processing push notifications for role {role}: {str(e)}",
                        title="Scheduled Order Notification - Push Error",
                    )

        except Exception as e:
            frappe.log_error(
                message=f"Error sending notification to role {role}: {str(e)}",
                title="Scheduled Order Notification - Role Error",
            )

    # Commit the transaction
    frappe.db.commit()

    return notifications_sent


def send_reservation_reminders():
    """
    Send 24-hour reminder emails for table reservations.
    Runs every hour.

    Conditions:
    - Reservation Status: Confirmed
    - Reservation Date + Time: Exactly 24 hours from now (±1 hour window)
    - Reminder Email not already sent
    """
    from frappe.utils import now_datetime, add_to_date, get_datetime

    # Get current datetime
    current_datetime = now_datetime()

    # Calculate target time (24 hours from now, with 1-hour window on either side)
    target_time_start = add_to_date(current_datetime, hours=23)
    target_time_end = add_to_date(current_datetime, hours=25)

    # Query confirmed reservations scheduled 24 hours from now
    reservations = frappe.get_all(
        "Table Reservation",
        filters={"status": "Confirmed", "reminder_email_sent": 0},
        fields=["name", "reservation_date", "reservation_time", "guest_name", "email"],
    )

    if not reservations:
        frappe.logger().debug("No confirmed reservations found for 24h reminder")
        return

    # Filter reservations within the 24-hour window
    reminders_sent = 0
    for reservation in reservations:
        try:
            # Check if reservation date and time exist
            if not reservation.reservation_date or not reservation.reservation_time:
                continue

            # Combine reservation date and time
            reservation_datetime = get_datetime(
                f"{reservation.reservation_date} {reservation.reservation_time}"
            )

            # Check if reservation falls within the 24-hour reminder window
            if target_time_start <= reservation_datetime <= target_time_end:
                # Import the send function from the doctype
                from excel_restaurant_pos.excel_restaurant_pos.doctype.table_reservation.table_reservation import (
                    send_24h_reminder_email,
                )

                # Send reminder email
                send_24h_reminder_email(reservation.name)
                reminders_sent += 1

                frappe.logger().info(
                    f"Sent 24h reminder for reservation: {reservation.name} "
                    f"(Guest: {reservation.guest_name}, Time: {reservation.reservation_time})"
                )

        except Exception as e:
            frappe.log_error(
                message=f"Error processing 24h reminder for reservation {reservation.name}: {str(e)}",
                title="Reservation 24h Reminder Error",
            )
            continue

    if reminders_sent > 0:
        frappe.logger().info(
            f"Sent {reminders_sent} reservation 24-hour reminder emails"
        )
