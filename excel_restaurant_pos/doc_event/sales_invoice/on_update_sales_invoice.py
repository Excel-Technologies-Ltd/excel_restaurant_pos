"""Document event handlers for Sales Invoice on_update event."""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, getdate, get_datetime


def on_update_sales_invoice(doc, method: str):
    """
    Send push notifications based on ArcPOS Settings configuration
    when Sales Invoice is updated.

    This handler:
    1. Gets push notification permissions from ArcPOS Settings
    2. Checks each rule against the current document
    3. Sends push and system notifications to users with matching roles
    """
    try:
        # Send Delivery or Pickup Notification
        # Get ArcPOS Settings
        settings = frappe.get_doc("ArcPOS Settings", "ArcPOS Settings")
        print("\n\n Duration : ", settings.send_email_after_delivery, "\n\n\n")
        template = settings.delivery_or_pickup_template

        if template:
            order_status = doc.get("custom_order_status") or ""
            service_type = doc.get("custom_service_type") or ""

            # Check if conditions match for sending notification
            should_send = False
            delay_seconds = 0

            if order_status == "Delivered" and service_type == "Delivery":
                should_send = True
                # Duration field stores value in seconds
                delay_seconds = int(settings.send_email_after_delivery or 0)
            elif order_status == "Picked Up" and service_type == "Pickup":
                should_send = True
                # Duration field stores value in seconds
                delay_seconds = int(settings.send_email_after_pickup or 0)

            print("Order Status ",order_status,"Delay (seconds): ", delay_seconds)
            if should_send:
                if delay_seconds and delay_seconds > 0:
                    # Schedule notification with delay on long queue to avoid blocking short queue workers
                    print(f"\n\n Scheduling delayed notification ({delay_seconds}s) \n\n")
                    frappe.enqueue(
                        send_delivery_pickup_notification,
                        queue="long",
                        timeout=max(300, delay_seconds + 120),
                        enqueue_after_commit=True,
                        at_front=False,
                        job_id=f"delivery_pickup_notification_{doc.name}",
                        sales_invoice_name=doc.name,
                        template_name=template,
                        delay_seconds=delay_seconds
                    )
                    print(f"Scheduled delivery/pickup notification for {doc.name} after {delay_seconds} seconds")
                else:
                    # Send notification immediately
                    print("\n\n This Condition is Working immediately \n\n")
                    frappe.enqueue(
                        send_delivery_pickup_notification,
                        queue="short",
                        timeout=300,
                        enqueue_after_commit=True,
                        sales_invoice_name=doc.name,
                        template_name=template
                    )
                    print(f"Queued immediate delivery/pickup notification for {doc.name}")
        else:
            print("Delivery and Pickup Template is missing in ArcPOS Settings")

        # Check for scheduled delivery/pickup 30 minutes before notification
        check_scheduled_notification_30min_before(doc, settings)

        # Prevent duplicate notifications using Redis cache
        # Key includes doc name and modified timestamp so different saves are processed independently
        # while duplicate hook triggers within the same save (same modified) are still deduplicated
        cache_key = f"arcpos_notification_processing_{doc.name}_{doc.modified}"
        if frappe.cache().get_value(cache_key):
            print(f"Notification already being processed for {doc.name} (modified={doc.modified}), skipping duplicate trigger")
            return

        # Mark as processing with 5 second TTL (short window to catch duplicate hook triggers)
        frappe.cache().set_value(cache_key, True, expires_in_sec=5)

        # Check if ArcPOS Settings exists
        print("\n\n on_update_sales_invoice called \n\n")
        if not frappe.db.exists("ArcPOS Settings", "ArcPOS Settings"):
            frappe.log_error(
                "ArcPOS Settings not found",
                "Push Notification - Settings Missing"
            )
            return

        

        # Check if there are any notification rules configured
        if not settings.role_wise_permission:
            frappe.log_error(
                "No push notification rules configured in ArcPOS Settings",
                "Push Notification - No Rules"
            )
            return

        # Log document details for debugging
        print(f"Processing notifications for Sales Invoice: {doc.name}")
        print(f"Order From: {doc.get('custom_order_from')}")
        print(f"Order Status: {doc.get('custom_order_status')}")
        print(f"Service Type: {doc.get('custom_service_type')}")
        print(f"Order Type: {doc.get('custom_order_type')}")

        # Process each notification rule
        matched_rules = 0
        for rule in settings.role_wise_permission:
            if should_send_notification(doc, rule):
                matched_rules += 1
                print(f"Rule matched for role: {rule.if_role}")
                # Enqueue notification sending to avoid blocking the save
                print(f"Enqueueing notification job for {doc.name} role {rule.if_role}...")
                job = frappe.enqueue(
                    send_notification_to_role_async,
                    queue="short",
                    timeout=300,
                    sales_invoice_name=doc.name,
                    rule_data={
                        "if_role": rule.if_role,
                        "if_order_from": rule.if_order_from,
                        "if_order_status": rule.if_order_status,
                        "if_service_type": rule.if_service_type,
                        "if_order_type": rule.if_order_type,
                        "if_order_schedule_type": rule.if_order_schedule_type,
                        "if_delivery_partner_status": rule.if_delivery_partner_status,
                        "item_is_new_order_item": rule.item_is_new_order_item,
                    }
                )
                print(f"Job enqueued: {job}")
                # Log to Error Log for production visibility
                frappe.log_error(
                    message=f"Document: {doc.name}\nRole: {rule.if_role}",
                    title="PN - Job Enqueued"
                )

        if matched_rules == 0:
            print(f"No notification rules matched for Sales Invoice: {doc.name}")

    except Exception as e:
        frappe.log_error(
            f"Error in on_update_sales_invoice: {str(e)}\nDocument: {doc.name}",
            "Push Notification Error"
        )


def should_send_notification(doc, rule):
    """
    Check if the current document matches the notification rule conditions.

    Args:
        doc: Sales Invoice document
        rule: ArcPOS Push Notification child table row or dict

    Returns:
        bool: True if all conditions match, False otherwise
    """
    # Get rule values (support both dict and object)
    if_role = rule.get("if_role") if isinstance(rule, dict) else rule.if_role
    if_order_from = rule.get("if_order_from") if isinstance(rule, dict) else rule.if_order_from
    if_order_status = rule.get("if_order_status") if isinstance(rule, dict) else rule.if_order_status
    if_service_type = rule.get("if_service_type") if isinstance(rule, dict) else rule.if_service_type
    if_order_type = rule.get("if_order_type") if isinstance(rule, dict) else rule.if_order_type
    if_order_schedule_type = rule.get("if_order_schedule_type") if isinstance(rule, dict) else rule.if_order_schedule_type
    if_delivery_partner_status = rule.get("if_delivery_partner_status") if isinstance(rule, dict) else rule.if_delivery_partner_status
    item_is_new_order_item = rule.get("item_is_new_order_item") if isinstance(rule, dict) else rule.item_is_new_order_item

    # Check if role is specified
    if not if_role:
        print("No role specified in rule, skipping")
        return False

    # Check Order From condition
    if if_order_from:
        doc_order_from = doc.get("custom_order_from") or ""
        # Support comma-separated values - all are valid
        allowed_order_from = [x.strip() for x in if_order_from.split(",") if x.strip()]
        if doc_order_from not in allowed_order_from:
            print(f"Order From mismatch: {doc_order_from} not in {allowed_order_from}")
            return False

    # Check Order Status condition
    if if_order_status:
        doc_order_status = doc.get("custom_order_status") or ""
        # Support comma-separated values - all are valid
        allowed_statuses = [x.strip() for x in if_order_status.split(",") if x.strip()]
        if doc_order_status not in allowed_statuses:
            print(f"Order Status mismatch: {doc_order_status} not in {allowed_statuses}")
            return False

    # Check Service Type condition
    if if_service_type:
        doc_service_type = doc.get("custom_service_type") or ""
        # Support comma-separated values - all are valid
        allowed_service_types = [x.strip() for x in if_service_type.split(",") if x.strip()]
        if doc_service_type not in allowed_service_types:
            print(f"Service Type mismatch: {doc_service_type} not in {allowed_service_types}")
            return False

    # Check Order Type condition
    if if_order_type:
        doc_order_type = doc.get("custom_order_type") or ""
        # Support comma-separated values - all are valid
        allowed_order_types = [x.strip() for x in if_order_type.split(",") if x.strip()]
        if doc_order_type not in allowed_order_types:
            print(f"Order Type mismatch: {doc_order_type} not in {allowed_order_types}")
            return False

    # Check Order Schedule Type condition
    if if_order_schedule_type:
        doc_order_schedule_type = doc.get("custom_order_schedule_type") or ""
        # Support comma-separated values - all are valid
        allowed_order_schedule_types = [x.strip() for x in if_order_schedule_type.split(",") if x.strip()]
        if doc_order_schedule_type not in allowed_order_schedule_types:
            print(f"Order Schedule Type mismatch: {doc_order_schedule_type} not in {allowed_order_schedule_types}")
            return False

    # Check Delivery Partner Status condition
    if if_delivery_partner_status:
        doc_delivery_partner_status = doc.get("custom_delivery_partner_status") or ""
        allowed_delivery_partner_statuses = [x.strip() for x in if_delivery_partner_status.split(",") if x.strip()]
        if doc_delivery_partner_status not in allowed_delivery_partner_statuses:
            print(f"Delivery Partner Status mismatch: {doc_delivery_partner_status} not in {allowed_delivery_partner_statuses}")
            return False

    # Check if notification should only be sent for new order items
    if item_is_new_order_item:
        has_new_order_item = False
        items = doc.get("items") or []
        print(f"Checking {len(items)} items for custom_new_ordered_item...")
        for item in items:
            # Get value - handle both dict and document object
            new_order_item_value = item.get("custom_new_ordered_item") if hasattr(item, "get") else getattr(item, "custom_new_ordered_item", 0)
            print(f"  Item: {item.get('item_code') if hasattr(item, 'get') else item.item_code}, custom_new_ordered_item={new_order_item_value} (type: {type(new_order_item_value).__name__})")
            if new_order_item_value == 1 or new_order_item_value == True:
                has_new_order_item = True
                break
        if not has_new_order_item:
            print(f"New Order Item check failed: No items with custom_new_ordered_item=1 found")
            return False
        print(f"New Order Item check passed: Found item(s) with custom_new_ordered_item=1")

    # All conditions matched
    print(f"All conditions matched for role: {if_role}")
    return True


def send_notification_to_role_async(sales_invoice_name, rule_data):
    """
    Async wrapper for sending notifications (called from queue).

    Args:
        sales_invoice_name: Name of the Sales Invoice document
        rule_data: Dictionary containing rule data
    """
    # Log immediately when worker picks up the job
    role = rule_data.get("if_role", "unknown")
    print(f"\n\n=== ASYNC NOTIFICATION START ===")
    print(f"Sales Invoice: {sales_invoice_name}")
    print(f"Rule: {rule_data}")
    frappe.log_error(
        message=f"Document: {sales_invoice_name}\nRole: {role}",
        title="PN - Worker Started"
    )

    try:
        # Get the document
        doc = frappe.get_doc("Sales Invoice", sales_invoice_name)

        # Deduplication check at async level using cache
        # Include order status so notifications for different status transitions aren't blocked
        order_status_for_key = doc.get("custom_order_status") or ""
        async_cache_key = f"arcpos_async_notification_{sales_invoice_name}_{role}_{order_status_for_key}"
        if frappe.cache().get_value(async_cache_key):
            print(f"Async notification already processed for {sales_invoice_name} role {role} status {order_status_for_key}, skipping")
            frappe.log_error(
                message=f"Document: {sales_invoice_name}\nRole: {role}\nStatus: {order_status_for_key}",
                title="PN - Duplicate Skipped"
            )
            return

        # Mark as processed with 30 second TTL
        frappe.cache().set_value(async_cache_key, True, expires_in_sec=30)
        print(f"Document loaded successfully: {doc.name}")

        # Send notifications
        send_notification_to_role(doc, rule_data)

        # Commit the transaction
        frappe.db.commit()
        print(f"=== ASYNC NOTIFICATION SUCCESS ===\n\n")
        frappe.log_error(
            message=f"Document: {sales_invoice_name}\nRole: {role}",
            title="PN - Success"
        )
    except Exception as e:
        print(f"!!! ERROR in send_notification_to_role_async: {str(e)}")
        import traceback
        print(traceback.format_exc())
        frappe.log_error(
            message=f"Error: {str(e)}\nDocument: {sales_invoice_name}\nRole: {role}\n\n{traceback.format_exc()}",
            title="PN - Error"
        )
        frappe.db.rollback()


def send_notification_to_role(doc, rule):
    """
    Send push notification and system notification to users with the specified role.

    Args:
        doc: Sales Invoice document
        rule: ArcPOS Push Notification child table row or dict
    """
    # Get rule values (support both dict and object)
    if_role = rule.get("if_role") if isinstance(rule, dict) else rule.if_role
    print(f"\n--- Sending notification for role: {if_role} ---")

    try:
        # Find all users with the specified role
        users = frappe.db.sql(
            """
            SELECT DISTINCT parent as user
            FROM `tabHas Role`
            WHERE role = %(role)s
            AND parent NOT IN ('Administrator', 'Guest')
            """,
            {"role": if_role},
            as_dict=True
        )

        if not users:
            print(f"!!! No users found with role: {if_role}")
            frappe.log_error(
                f"No users found with role: {if_role}",
                "Push Notification - No Users"
            )
            return

        user_emails = [user.user for user in users]
        print(f"Found {len(user_emails)} users with role {if_role}: {user_emails}")

        # Prepare notification content
        title = get_notification_title(doc, rule)
        body = get_notification_body(doc, rule)
        print(f"Notification Title: {title}")
        print(f"Notification Body: {body}")

        # ALWAYS save system notifications for all users (even if they don't have tokens)
        # Track users who actually received notifications (for push notification deduplication)
        users_notified = []

        print(f"\n Sending SYSTEM NOTIFICATIONS to {len(user_emails)} users:")
        system_notifications_sent = 0
        for user_email in user_emails:
            print(f"  → Attempting to send system notification to: {user_email}")
            try:
                # Check if notification already exists for this user/document in last 30 seconds
                thirty_seconds_ago = add_to_date(now_datetime(), seconds=-30)

                existing_notification = frappe.db.exists(
                    "Notification Log",
                    {
                        "for_user": user_email,
                        "document_type": "Sales Invoice",
                        "document_name": doc.name,
                        "creation": [">=", thirty_seconds_ago]
                    }
                )

                if existing_notification:
                    print(f"    ⊘ SKIPPED: Recent notification already exists for: {user_email}")
                    continue

                notification = frappe.get_doc({
                    "doctype": "Notification Log",
                    "for_user": user_email,
                    "from_user": frappe.session.user,
                    "subject": title,
                    "email_content": body,
                    "document_type": "Sales Invoice",
                    "document_name": doc.name,
                    "type": "Alert",
                    "read": 0
                })
                notification.insert(ignore_permissions=True)
                system_notifications_sent += 1
                users_notified.append(user_email)  # Track this user for push notifications
                frappe.publish_realtime('sales_invoice_notification_'+user_email, data = {
                    'title': title,
                    'body': body,
                    'document_type': 'Sales Invoice',
                    'document_name': doc.name
                },
                )
                print(f"    ✓ SUCCESS: System notification saved for: {user_email}")
            except Exception as e:
                print(f"    ✗ FAILED: Error saving system notification for {user_email}: {str(e)}")
                frappe.log_error(
                    f"Error saving system notification for user {user_email}: {str(e)}",
                    "System Notification Error"
                )

        print(f"\n System notifications sent: {system_notifications_sent}/{len(user_emails)}\n")

        # Skip push notifications if no users received system notifications
        if not users_notified:
            print("No users received new system notifications, skipping push notifications")
            print(f"--- Notification complete (no new notifications) ---\n")
            return

        # Try to send push notifications if Expo SDK is available
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
            print("Expo Server SDK not installed, skipping push notifications")
            frappe.log_error(
                f"Expo Server SDK not installed. Install with: pip install exponent-server-sdk",
                "Push Notification - SDK Missing"
            )
            has_expo = False

        if not has_expo:
            print(f"--- Notification complete (system only) ---\n")
            return

        # Get Expo tokens only for users who received new system notifications
        token_docs = frappe.get_all(
            "ArcPOS Notification Token",
            filters={"user": ["in", users_notified]},
            fields=["name", "user"]
        )

        print(f"Found {len(token_docs)} users with notification token documents")
        # Log for production debugging
        frappe.logger("push_notification").info(
            f"Push notification for {doc.name}: users_notified={users_notified}, token_docs_count={len(token_docs)}"
        )

        if not token_docs:
            print("  No users with notification tokens found, skipping push notifications")
            frappe.log_error(
                f"No push tokens found for users: {users_notified}. Document: {doc.name}",
                "Push Notification - No Tokens"
            )
            print(f"--- Notification complete (system only) ---\n")
            return

        # Prepare push notification messages
        print(f"\n Preparing PUSH NOTIFICATIONS:")
        push_messages = []
        token_to_user_map = {}

        for token_doc in token_docs:
            print(f"  → Processing tokens for user: {token_doc.user}")

            # Get all tokens from the token_list child table
            user_tokens = frappe.get_all(
                "Push Token List",
                filters={"parent": token_doc.name, "parenttype": "ArcPOS Notification Token"},
                fields=["token"]
            )

            if not user_tokens:
                print(f"    ✗ No tokens found in token_list for: {token_doc.user}")
                continue

            for token_row in user_tokens:
                if token_row.token:
                    # Validate Expo push token format
                    if not PushClient.is_exponent_push_token(token_row.token):
                        print(f"    ✗ INVALID token format for: {token_doc.user}")
                        frappe.log_error(
                            f"Invalid Expo token for user {token_doc.user}: {token_row.token}",
                            "Invalid Expo Token"
                        )
                        continue

                    # Create push message
                    push_message = PushMessage(
                        to=token_row.token,
                        title=title,
                        body=body,
                        data={
                            "document_type": "Sales Invoice",
                            "document_name": doc.name,
                            "order_status": doc.get("custom_order_status") or "",
                            "order_from": doc.get("custom_order_from") or "",
                            "service_type": doc.get("custom_service_type") or "",
                            "order_type": doc.get("custom_order_type") or "",
                        },
                        sound="default",
                        priority="high"
                    )

                    push_messages.append(push_message)
                    token_to_user_map[token_row.token] = token_doc.user
                    print(f"    ✓ Push message prepared for: {token_doc.user}")

        print(f"\n Total push messages to send: {len(push_messages)}")
        # Log for production debugging
        frappe.logger("push_notification").info(
            f"Push messages prepared for {doc.name}: count={len(push_messages)}, users={list(token_to_user_map.values())}"
        )

        # Send push notifications if tokens are available
        if push_messages:
            push_client = PushClient()
            push_sent_count = 0

            print(f"\n Sending push notifications via Expo...")
            frappe.logger("push_notification").info(f"Starting Expo push for {doc.name}")
            try:
                # Send notifications in chunks (Expo recommends max 100 per request)
                chunk_size = 100
                for i in range(0, len(push_messages), chunk_size):
                    chunk = push_messages[i:i + chunk_size]
                    print(f"  → Sending chunk {i//chunk_size + 1} ({len(chunk)} messages)...")

                    try:
                        responses = push_client.publish_multiple(chunk)

                        # Process responses
                        for response, message in zip(responses, chunk):
                            user = token_to_user_map.get(message.to)
                            try:
                                response.validate_response()
                                push_sent_count += 1
                                print(f"      ✓ Push notification SENT to: {user}")
                            except DeviceNotRegisteredError:
                                # Token is no longer valid
                                print(f"      ✗ Device not registered: {user}")
                                frappe.log_error(
                                    f"Device not registered: {user}",
                                    "Push Notification - Invalid Token"
                                )
                            except PushTicketError as exc:
                                print(f"      ✗ Push ticket error for {user}: {exc.message}")
                                frappe.log_error(
                                    f"Push ticket error for {user}: {exc.message}",
                                    "Push Notification Error"
                                )
                    except PushServerError as exc:
                        print(f"      ✗ Push server error: {str(exc)}")
                        frappe.log_error(
                            f"Push server error: {str(exc)}",
                            "Expo Push Notification Error"
                        )
            except Exception as exc:
                print(f"  ✗ Error sending push notifications: {str(exc)}")
                frappe.log_error(
                    f"Error sending push notifications: {str(exc)}",
                    "Expo Push Notification Error"
                )

            print(f"\n Push notifications sent: {push_sent_count}/{len(push_messages)}")
            # Log result for production debugging
            frappe.logger("push_notification").info(
                f"Push result for {doc.name}: sent={push_sent_count}/{len(push_messages)}"
            )
        else:
            print("  No valid push messages to send")
            frappe.log_error(
                f"No valid push messages to send for {doc.name}. Token docs: {token_docs}",
                "Push Notification - No Messages"
            )

        print(f"\n=== Notification complete (system + push) ===\n")

    except Exception as e:
        rule_dict = rule if isinstance(rule, dict) else rule.as_dict()
        frappe.log_error(
            f"Error in send_notification_to_role: {str(e)}\nDocument: {doc.name}\nRule: {rule_dict}",
            "Push Notification Error"
        )


def get_notification_title(doc, rule):
    """
    Generate notification title based on the document.

    Args:
        doc: Sales Invoice document
        rule: ArcPOS Push Notification child table row

    Returns:
        str: Notification title
    """
    order_status = doc.get("custom_order_status") or "Updated"
    return f"Order {order_status}: {doc.name}"


def get_notification_body(doc, rule):
    """
    Generate notification body based on the document.

    Args:
        doc: Sales Invoice document
        rule: ArcPOS Push Notification child table row

    Returns:
        str: Notification body
    """
    parts = []

    # Add customer name
    if doc.customer:
        parts.append(f"Customer: {doc.customer}")

    # Add order details
    order_from = doc.get("custom_order_from")
    if order_from:
        parts.append(f"Order From: {order_from}")

    service_type = doc.get("custom_service_type")
    if service_type:
        parts.append(f"Service: {service_type}")

    # Add table info if available
    table_name = doc.get("custom_linked_table")
    if table_name:
        parts.append(f"Table: {table_name}")

    # Add grand total
    if doc.grand_total:
        parts.append(f"Total: {frappe.utils.fmt_money(doc.grand_total, currency=doc.currency)}")

    return " | ".join(parts) if parts else f"Sales Invoice {doc.name} has been updated."


def send_delivery_pickup_notification(sales_invoice_name, template_name, delay_seconds=0):
    """
    Send delivery or pickup notification to customer using the specified template.

    Args:
        sales_invoice_name: Name of the Sales Invoice document
        template_name: Name of the Notification Template to use
        delay_seconds: Number of seconds to wait before sending (Duration field value)
    """
    try:
        # Wait for the specified delay before sending
        if delay_seconds and delay_seconds > 0:
            import time
            print(f"Waiting {delay_seconds} seconds before sending notification for {sales_invoice_name}")
            time.sleep(delay_seconds)
            print(f"Delay complete, sending notification for {sales_invoice_name}")

        # Get the Sales Invoice document
        doc = frappe.get_doc("Sales Invoice", sales_invoice_name)

        # Get customer email
        customer_email = frappe.db.get_value("Customer", doc.customer, "email_id")
            

        if not customer_email:
            print(f"No customer email found for Sales Invoice {sales_invoice_name}")
            frappe.log_error(
                f"No customer email found for Sales Invoice {sales_invoice_name}",
                "Delivery/Pickup Notification - No Email"
            )
            return

        # Get the Email Template from database and render it
        email_template = frappe.get_doc("Email Template", template_name)
        template_args = {
            "doc": doc,
            "customer_name": doc.customer_name or doc.customer,
            "invoice_name": doc.name,
            "order_status": doc.get("custom_order_status") or "",
            "service_type": doc.get("custom_service_type") or "",
            "grand_total": frappe.utils.fmt_money(doc.grand_total, currency=doc.currency) if doc.grand_total else "",
        }
        subject = frappe.render_template(email_template.subject, template_args)
        message = frappe.render_template(email_template.response_html or email_template.response, template_args)

        # Send notification (header=None prevents Frappe from wrapping in its own email template)
        frappe.sendmail(
            recipients=[customer_email],
            subject=subject,
            message=message,
            header=None,
            now=True
        )

        print(f"Delivery/Pickup notification sent to {customer_email} for {sales_invoice_name}")
        frappe.log_error(
            f"Notification sent to {customer_email} for Sales Invoice {sales_invoice_name}",
            "Delivery/Pickup Notification - Success"
        )

    except Exception as e:
        frappe.log_error(
            f"Error sending delivery/pickup notification: {str(e)}\nSales Invoice: {sales_invoice_name}",
            "Delivery/Pickup Notification Error"
        )


def check_scheduled_notification_30min_before(doc, settings):
    """
    Check if current order needs 30-minute reminder notification for scheduled delivery/pickup.

    Conditions:
    - Service Type: Pickup OR Delivery
    - Order Status: Open, Accepted, Waiting, In kitchen, Preparing, Scheduled,
                    Ready to Deliver, Ready to Pickup, Handover to Delivery
    - Order Schedule Type: Scheduled Later
    - DeliveryDate: Current Date
    - Current Time: 30 minutes before DeliveryTime

    Args:
        doc: Sales Invoice document
        settings: ArcPOS Settings document
    """
    try:
        # Check basic conditions
        service_type = doc.get("custom_service_type") or ""
        order_status = doc.get("custom_order_status") or ""
        order_schedule_type = doc.get("custom_order_schedule_type") or ""
        delivery_date = doc.get("custom_delivery_date")
        delivery_time = doc.get("custom_delivery_time")

        # Check if this is a scheduled pickup/delivery order
        if service_type not in ["Pickup", "Delivery"]:
            return

        if order_schedule_type != "Scheduled Later":
            return

        # Check order status
        allowed_statuses = [
            "Open", "Accepted", "Waiting", "In kitchen", "Preparing", "Scheduled",
            "Ready to Deliver", "Ready to Pickup", "Handover to Delivery"
        ]
        if order_status not in allowed_statuses:
            return

        # Check if delivery date and time are set
        if not delivery_date or not delivery_time:
            return

        # Check if delivery date is today
        current_date = getdate(now_datetime())
        if delivery_date != current_date:
            return

        # Compare current time with delivery time
        # delivery_datetime = The scheduled delivery/pickup time from the invoice
        # current_datetime = Current system time
        delivery_datetime = get_datetime(f"{delivery_date} {delivery_time}")
        current_datetime = now_datetime()

        # Calculate how many minutes remain until delivery
        # Example: If delivery is at 9:30 PM and current time is 9:00 PM, time_diff_minutes = 30
        time_diff_minutes = (delivery_datetime - current_datetime).total_seconds() / 60

        # Send notification if we're exactly 30 minutes before delivery (±2 minute window)
        # This allows for slight timing variations in the update trigger
        if not (28 <= time_diff_minutes <= 32):
            return

        # Check cache to prevent duplicate notifications
        cache_key = f"scheduled_30min_notification_{doc.name}"
        if frappe.cache().get_value(cache_key):
            print(f"30-minute notification already sent for {doc.name}, skipping")
            return

        # Mark as notified (1-hour cache to prevent duplicates)
        frappe.cache().set_value(cache_key, True, expires_in_sec=3600)

        # Send notifications to matching roles
        send_scheduled_30min_notification(doc, settings)

        print(f"Sent 30-minute reminder notification for scheduled order: {doc.name} (Delivery time: {delivery_time})")

    except Exception as e:
        frappe.log_error(
            f"Error checking 30-minute notification: {str(e)}\nDocument: {doc.name}",
            "Scheduled 30-Min Notification Check Error"
        )


def send_scheduled_30min_notification(doc, settings):
    """
    Send system and push notifications for a scheduled delivery/pickup order 30 minutes before.

    Args:
        doc: Sales Invoice document
        settings: ArcPOS Settings document
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
        print("Expo Server SDK not installed for 30-min notification")

    # Find matching notification rules for scheduled orders
    matching_roles = set()
    for rule in settings.role_wise_permission:
        if not rule.if_role:
            continue

        # Check Service Type
        if rule.if_service_type:
            allowed_service_types = [x.strip() for x in rule.if_service_type.split(",") if x.strip()]
            if doc.custom_service_type not in allowed_service_types:
                continue

        # Check Order Schedule Type - must include "Scheduled Later"
        if rule.if_order_schedule_type:
            allowed_schedule_types = [x.strip() for x in rule.if_order_schedule_type.split(",") if x.strip()]
            if "Scheduled Later" not in allowed_schedule_types:
                continue
        else:
            # Skip rules that don't specify schedule type
            continue

        # Check Order Status (if specified)
        if rule.if_order_status:
            allowed_statuses = [x.strip() for x in rule.if_order_status.split(",") if x.strip()]
            if doc.custom_order_status not in allowed_statuses:
                continue

        # Check Order From (if specified)
        if rule.if_order_from:
            allowed_order_from = [x.strip() for x in rule.if_order_from.split(",") if x.strip()]
            if doc.custom_order_from not in allowed_order_from:
                continue

        # Check Order Type (if specified)
        if rule.if_order_type:
            allowed_order_types = [x.strip() for x in rule.if_order_type.split(",") if x.strip()]
            if doc.custom_order_type not in allowed_order_types:
                continue

        # Check Delivery Partner Status (if specified)
        if rule.if_delivery_partner_status:
            allowed_dp_statuses = [x.strip() for x in rule.if_delivery_partner_status.split(",") if x.strip()]
            if (doc.custom_delivery_partner_status or "") not in allowed_dp_statuses:
                continue

        # Rule matches - add role
        matching_roles.add(rule.if_role)

    if not matching_roles:
        print(f"No matching notification rules for 30-min reminder: {doc.name}")
        return

    # Gather all users from matching roles (used as email fallback)
    role_user_emails = list(set(frappe.db.sql(
        """
        SELECT DISTINCT parent as user
        FROM `tabHas Role`
        WHERE role IN %(roles)s
        AND parent NOT IN ('Administrator', 'Guest')
        """,
        {"roles": tuple(matching_roles)},
        as_dict=True,
    )))
    role_user_emails = [u.user for u in role_user_emails]

    # Send email notification — to override emails if set, else to role-wise users
    if settings.scheduled_order_reminder_template:
        try:
            send_scheduled_reminder_email(
                doc, settings.scheduled_order_reminder_template, settings,
                role_user_emails=role_user_emails,
            )
        except Exception as e:
            frappe.log_error(
                f"Error sending scheduled reminder email: {str(e)}\nDocument: {doc.name}",
                "Scheduled Reminder Email Error"
            )

    # Prepare notification content
    service_type = doc.custom_service_type or "Delivery/Pickup"
    delivery_time = doc.custom_delivery_time
    customer_name = doc.customer_name or doc.customer

    title = f"Scheduled {service_type} - 30 Minutes Reminder : {doc.name}"
    body = (
        f"Order {doc.name} for {customer_name} is scheduled for "
        f"{service_type.lower()} at {delivery_time}. "
        f"Please prepare the order."
    )

    # Send notifications to each matching role
    for role in matching_roles:
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
                as_dict=True
            )

            if not users:
                print(f"No users found with role: {role}")
                continue

            user_emails = [user.user for user in users]
            print(f"Sending 30-min reminder to {len(user_emails)} users with role {role}")

            # Send system notifications to all users
            for user_email in user_emails:
                try:
                    # Check if notification already exists to prevent duplicates
                    thirty_seconds_ago = add_to_date(now_datetime(), seconds=-30)
                    existing_notification = frappe.db.exists(
                        "Notification Log",
                        {
                            "for_user": user_email,
                            "document_type": "Sales Invoice",
                            "document_name": doc.name,
                            "subject": title,
                            "creation": [">=", thirty_seconds_ago]
                        }
                    )

                    if existing_notification:
                        continue

                    notification = frappe.get_doc({
                        "doctype": "Notification Log",
                        "for_user": user_email,
                        "from_user": frappe.session.user or "Administrator",
                        "subject": title,
                        "email_content": body,
                        "document_type": "Sales Invoice",
                        "document_name": doc.name,
                        "type": "Alert",
                        "read": 0
                    })
                    notification.insert(ignore_permissions=True)

                    # Publish realtime event
                    frappe.publish_realtime(
                        'sales_invoice_notification_' + user_email,
                        data={
                            'title': title,
                            'body': body,
                            'document_type': 'Sales Invoice',
                            'document_name': doc.name
                        }
                    )
                    print(f"  ✓ System notification sent to: {user_email}")

                except Exception as e:
                    frappe.log_error(
                        f"Error sending 30-min system notification to {user_email}: {str(e)}",
                        "Scheduled 30-Min Notification Error"
                    )

            # Send push notifications if Expo is available
            if has_expo:
                try:
                    # Get Expo tokens for users
                    token_docs = frappe.get_all(
                        "ArcPOS Notification Token",
                        filters={"user": ["in", user_emails]},
                        fields=["name", "user"]
                    )

                    if token_docs:
                        push_messages = []
                        for token_doc_name in [t.name for t in token_docs]:
                            token_doc = frappe.get_doc("ArcPOS Notification Token", token_doc_name)

                            # Get tokens from child table
                            if token_doc.token_list:
                                for token_row in token_doc.token_list:
                                    if token_row.token and PushClient.is_exponent_push_token(token_row.token):
                                        push_messages.append(
                                            PushMessage(
                                                to=token_row.token,
                                                title=title,
                                                body=body,
                                                data={
                                                    "document_type": "Sales Invoice",
                                                    "document_name": doc.name,
                                                    "notification_type": "scheduled_30min_reminder",
                                                    "order_status": doc.custom_order_status or "",
                                                    "service_type": doc.custom_service_type or "",
                                                    "delivery_time": str(doc.custom_delivery_time)
                                                },
                                                sound="default",
                                                priority="high"
                                            )
                                        )

                        # Send push notifications in chunks
                        if push_messages:
                            push_client = PushClient()
                            chunk_size = 100
                            for i in range(0, len(push_messages), chunk_size):
                                chunk = push_messages[i:i + chunk_size]
                                try:
                                    responses = push_client.publish_multiple(chunk)
                                    for response in responses:
                                        try:
                                            response.validate_response()
                                        except DeviceNotRegisteredError:
                                            pass  # Token expired, ignore
                                        except (PushTicketError, PushServerError) as exc:
                                            print(f"Push notification error: {exc.message}")
                                except Exception as e:
                                    frappe.log_error(
                                        f"Error sending 30-min push notification chunk: {str(e)}",
                                        "Scheduled 30-Min Push Error"
                                    )

                            print(f"  ✓ Push notifications sent to role: {role}")

                except Exception as e:
                    frappe.log_error(
                        f"Error processing 30-min push notifications for role {role}: {str(e)}",
                        "Scheduled 30-Min Push Error"
                    )

        except Exception as e:
            frappe.log_error(
                f"Error sending 30-min notification to role {role}: {str(e)}",
                "Scheduled 30-Min Notification Error"
            )

    # Commit the transaction
    frappe.db.commit()
    print(f"30-minute reminder notification completed for {doc.name}")


def send_scheduled_reminder_email(doc, template_name, settings=None, role_user_emails=None):
    """
    Send scheduled order reminder email 30 minutes before delivery/pickup.

    Recipients:
      - If 'Scheduled Order Email Send To' is set in ArcPOS Settings, send to those
        comma-separated addresses.
      - Otherwise, fall back to the role-wise users from matching notification rules.

    Args:
        doc: Sales Invoice document
        template_name: Name of the Email Template to use
        settings: ArcPOS Settings document (optional; fetched if not provided)
        role_user_emails: List of user emails from matching Role Wise Permission rules
    """
    try:
        if settings is None:
            settings = frappe.get_doc("ArcPOS Settings", "ArcPOS Settings")

        # Resolve recipients — read directly from DB to avoid stale Document cache
        override_emails = frappe.db.get_single_value("ArcPOS Settings", "scheduled_order_email_send_to") or ""

        if override_emails.strip():
            recipients = [e.strip() for e in override_emails.split(",") if e.strip()]
        else:
            recipients = role_user_emails or []
            if not recipients:
                print(f"No role-wise users found for scheduled reminder: {doc.name}")
                frappe.log_error(
                    f"No role-wise users found for Sales Invoice {doc.name}",
                    "Scheduled Reminder Email - No Recipients"
                )
                return

        # Get the Email Template and render it
        email_template = frappe.get_doc("Email Template", template_name)

        # Prepare template arguments
        service_type = doc.custom_service_type or "Delivery/Pickup"
        delivery_time = doc.custom_delivery_time
        delivery_date = doc.custom_delivery_date

        template_args = {
            "doc": doc,
            "customer_name": doc.customer_name or doc.customer,
            "invoice_name": doc.name,
            "order_status": doc.custom_order_status or "",
            "service_type": service_type,
            "delivery_date": delivery_date,
            "delivery_time": delivery_time,
            "grand_total": frappe.utils.fmt_money(doc.grand_total, currency=doc.currency) if doc.grand_total else "",
        }

        # Render subject and message
        subject = frappe.render_template(email_template.subject, template_args)
        message = frappe.render_template(email_template.response_html or email_template.response, template_args)

        # Send email
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message,
            header=None,
            now=True
        )

        print(f"Scheduled reminder email sent to {recipients} for {doc.name}")
        frappe.log_error(
            f"Scheduled reminder email sent to {recipients} for Sales Invoice {doc.name}",
            "Scheduled Reminder Email - Success"
        )

    except Exception as e:
        frappe.log_error(
            f"Error sending scheduled reminder email: {str(e)}\nSales Invoice: {doc.name}",
            "Scheduled Reminder Email Error"
        )
