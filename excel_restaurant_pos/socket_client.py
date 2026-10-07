import socketio
import os
import requests

# Configuration
ENVIRONMENT = os.getenv("ENV", "production")
BASE_URL = "https://arcpos.aninda.me"
SITE_NAME = "arcpos.aninda.me"

# Bearer Token - Replace with your actual token
BEARER_TOKEN = os.getenv("BEARER_TOKEN", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYXptaW5AZXhjZWxiZC5jb20iLCJleHAiOjE3Njk1ODQzNTQsImlhdCI6MTc2OTU4MDc1NCwidHlwZSI6ImFjY2VzcyJ9.s4rufCcEAK6odLh5CwlWEAbRI5lg5ULIWY8eP0mpEwQ")

print("=" * 60)
print("Socket.IO Client - Bearer Token Authentication")
print("=" * 60)
print(f" URL: {BASE_URL}")
print(f" Site: {SITE_NAME}")
print(f" Token: {BEARER_TOKEN[:40]}...")
print("=" * 60)
print()

# Create Socket.IO client
sio = socketio.Client(logger=True, engineio_logger=True)


def fetch_notifications():
    """Fetch the last 20 notifications from the API"""
    try:
        response = requests.get(
            f"{BASE_URL}/api/method/excel_restaurant_pos.api.notification.get_notification_list.my_notifications",
            headers={
                'Authorization': f'Bearer {BEARER_TOKEN}',
                'X-Frappe-Site-Name': SITE_NAME
            }
        )
        response.raise_for_status()
        data = response.json()
        return data.get('message', {})
    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return None


@sio.event
def connect():
    print()
    print("=" * 60)
    print(f" Socket connected! ID: {sio.sid}")
    print("=" * 60)
    print()

    # Join user-specific room to receive notifications
    user_email = "azmin@excelbd.com"  # Extracted from your token
    user_room = f"{SITE_NAME}:user:{user_email}"

    print(f" Joining user room: {user_room}")
    print(f" Listening for notifications...")
    print()

    # Fetch last 20 notifications on connect
    print("Fetching last 20 notifications...")
    result = fetch_notifications()
    if result:
        notifications = result.get('notifications', [])
        unread_count = result.get('unread_count', 0)
        print(f"Unread count: {unread_count}")
        print(f"Total fetched: {len(notifications)}")
        print("-" * 60)
        for notif in notifications:
            read_status = "Read" if notif.get('read') else "Unread"
            print(f"[{read_status}] {notif.get('subject', 'No subject')}")
            print(f"   From: {notif.get('from_user', 'N/A')} | Type: {notif.get('type', 'N/A')}")
            print(f"   Created: {notif.get('creation', 'N/A')}")
            print("-" * 60)
    print()


@sio.event
def connect_error(data):
    print()
    print("=" * 60)
    print(f" Socket connection failed: {data}")
    print("=" * 60)
    print()


@sio.event
def disconnect():
    print()
    print("=" * 60)
    print("  Disconnected from server")
    print("=" * 60)
    print()


# Notification event handlers
@sio.on('sales_invoice_notification_azmin@excelbd.com')
def on_notification(data):
    print()
    print("" + "=" * 59)
    print("NOTIFICATION RECEIVED")
    print("=" * 60)
    print(f"Type: {data.get('type', 'N/A')}")
    print(f"Message: {data.get('message', data)}")
    if isinstance(data, dict):
        for key, value in data.items():
            if key not in ['type', 'message']:
                print(f"{key}: {value}")
    print("=" * 60)
    print()


@sio.on('msgprint')
def on_msgprint(data):
    print()
    print("" + "=" * 59)
    print("MESSAGE PRINT")
    print("=" * 60)
    print(f"Message: {data.get('message', data) if isinstance(data, dict) else data}")
    if isinstance(data, dict):
        print(f"Indicator: {data.get('indicator', 'blue')}")
        if data.get('title'):
            print(f"Title: {data.get('title')}")
    print("=" * 60)
    print()


@sio.on('eval_js')
def on_eval_js(data):
    print()
    print("⚡" + "=" * 59)
    print("EVAL JS")
    print("=" * 60)
    print(f"Script: {data}")
    print("=" * 60)
    print()


@sio.on('list_update')
def on_list_update(data):
    print()
    print("" + "=" * 59)
    print("LIST UPDATE")
    print("=" * 60)
    print(f"DocType: {data.get('doctype', 'N/A')}")
    print(f"Name: {data.get('name', 'N/A')}")
    print("=" * 60)
    print()


@sio.on('doc_update')
def on_doc_update(data):
    print()
    print("" + "=" * 59)
    print("DOCUMENT UPDATE")
    print("=" * 60)
    print(f"DocType: {data.get('doctype', 'N/A')}")
    print(f"Name: {data.get('name', 'N/A')}")
    print(f"Modified: {data.get('modified', 'N/A')}")
    print("=" * 60)
    print()


@sio.on('new_email')
def on_new_email(data):
    print()
    print("" + "=" * 59)
    print("NEW EMAIL")
    print("=" * 60)
    print(f"Data: {data}")
    print("=" * 60)
    print()


# Catch all other events
@sio.on('*')
def catch_all(event, data):
    print()
    print("" + "=" * 59)
    print(f"EVENT: {event}")
    print("=" * 60)
    print(f"Data: {data}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    try:
        # Prepare headers with Bearer token
        headers = {
            'Authorization': f'Bearer {BEARER_TOKEN}',
            'X-Frappe-Site-Name': SITE_NAME
        }

        print(f"🔌 Connecting to Socket.IO at {BASE_URL}...")
        print(f"   Using Bearer token authentication")
        print()

        # Connect to Socket.IO
        sio.connect(
            BASE_URL,
            transports=['polling', 'websocket'],
            socketio_path='/socket.io',
            headers=headers
        )

        print(" Socket.IO connection established. Waiting for events...")
        print("   Press Ctrl+C to disconnect")
        print()

        # Wait for events
        sio.wait()

    except KeyboardInterrupt:
        print()
        print("  Interrupted by user")
        sio.disconnect()
    except Exception as e:
        print()
        print("=" * 60)
        print(f" Error: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
