"""
Socket.IO Test Publisher
Run this after starting the subscriber to trigger Frappe events.

Options:
1. Ping socket server (verify socket connectivity)
2. Update a document (triggers doc_update, list_update)
3. Create a Comment/Note (triggers doc_update)
4. Trigger via publish_realtime API
"""
import requests
import os
import json
from datetime import datetime

# Configuration
BASE_URL = os.getenv("SOCKET_URL", "https://arcpos.aninda.me")
SITE_NAME = os.getenv("SITE_NAME", "arcpos.aninda.me")
BEARER_TOKEN = os.getenv("BEARER_TOKEN", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYXptaW5AZXhjZWxiZC5jb20iLCJleHAiOjE3Njk1OTA1NjcsImlhdCI6MTc2OTU4Njk2NywidHlwZSI6ImFjY2VzcyJ9.KHYmGAHvyDgEn2bAV_gG_D1Ubbrw_LAQcjmYIrLS4Vw")
USER_EMAIL = os.getenv("USER_EMAIL", "azmin@excelbd.com")
NAMESPACE = f"/{SITE_NAME}"

print("=" * 60)
print("Socket.IO Test Publisher - Frappe Events")
print("=" * 60)
print(f"URL: {BASE_URL}")
print(f"Namespace: {NAMESPACE}")
print("=" * 60)
print()


def get_headers():
    return {
        'Authorization': f'Bearer {BEARER_TOKEN}',
        'X-Frappe-Site-Name': SITE_NAME,
        'Content-Type': 'application/json'
    }


def api_call(method, endpoint, data=None):
    """Make a Frappe API call."""
    url = f"{BASE_URL}/api/method/{endpoint}"
    try:
        if method == 'GET':
            response = requests.get(url, headers=get_headers(), params=data)
        else:
            response = requests.post(url, headers=get_headers(), json=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def test_socket_ping():
    """Connect to socket and send ping to verify socket connectivity."""
    import socketio

    print("Testing socket connection with ping...")

    sio = socketio.Client(logger=False, engineio_logger=False)
    result = {'connected': False, 'pong_received': False}

    @sio.event
    def connect():
        result['connected'] = True
        print(f"[CONNECTED] Session ID: {sio.sid}")
        print("[SENDING] ping event...")
        sio.emit('ping')

    @sio.on('pong')
    def on_pong(data):
        result['pong_received'] = True
        print(f"[RECEIVED] pong: {data}")
        sio.disconnect()

    @sio.event
    def connect_error(data):
        print(f"[ERROR] Connection failed: {data}")

    try:
        headers = {
            'Authorization': f'Bearer {BEARER_TOKEN}',
            'X-Frappe-Site-Name': SITE_NAME,
            'Origin': BASE_URL,
        }

        sio.connect(
            BASE_URL,
            namespaces=[NAMESPACE],
            transports=['polling', 'websocket'],
            socketio_path='/socket.io',
            headers=headers
        )

        # Wait for pong or timeout
        sio.sleep(3)

        if result['connected'] and result['pong_received']:
            print("[SUCCESS] Socket ping/pong working!")
            return True
        elif result['connected']:
            print("[PARTIAL] Connected but no pong received")
            return True
        else:
            print("[FAILED] Could not connect")
            return False

    except Exception as e:
        print(f"[ERROR] {e}")
        return False
    finally:
        if sio.connected:
            sio.disconnect()


def test_api_ping():
    """Simple ping to verify API connectivity."""
    print("Pinging API server...")

    result = api_call('GET', 'frappe.ping')

    if result:
        print(f"[SUCCESS] Server responded: {result.get('message', 'pong')}")
        return True

    return False


def test_update_user_settings():
    """Update user settings to trigger a doc_update event."""
    print("Updating user settings...")

    # Get current user settings
    result = api_call('POST', 'frappe.client.get_value', {
        'doctype': 'User',
        'filters': {'name': USER_EMAIL},
        'fieldname': ['name', 'bio']
    })

    if result:
        print(f"Current user: {result}")

        # Update bio with timestamp to trigger change
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_result = api_call('POST', 'frappe.client.set_value', {
            'doctype': 'User',
            'name': USER_EMAIL,
            'fieldname': 'bio',
            'value': f'Socket test at {timestamp}'
        })

        if update_result:
            print("[SUCCESS] User bio updated - should trigger doc_update event")
            print("Check subscriber terminal for doc_update event")
            return True

    return False


def test_create_todo():
    """Create a ToDo item to trigger doc events."""
    print("Creating a ToDo item...")

    timestamp = datetime.now().strftime("%H:%M:%S")
    todo_data = {
        'doctype': 'ToDo',
        'description': f'Socket test item - {timestamp}',
        'status': 'Open',
        'priority': 'Medium',
        'allocated_to': USER_EMAIL
    }

    result = api_call('POST', 'frappe.client.insert', {'doc': json.dumps(todo_data)})

    if result:
        print(f"[SUCCESS] ToDo created: {result.get('message', {}).get('name', 'unknown')}")
        print("This should trigger doc_update and list_update events")
        print("Check subscriber terminal for events")
        return True

    return False


def test_create_comment():
    """Create a Comment to trigger events."""
    print("Creating a Comment...")

    timestamp = datetime.now().strftime("%H:%M:%S")
    comment_data = {
        'doctype': 'Comment',
        'comment_type': 'Comment',
        'reference_doctype': 'User',
        'reference_name': USER_EMAIL,
        'content': f'Socket test comment at {timestamp}'
    }

    result = api_call('POST', 'frappe.client.insert', {'doc': json.dumps(comment_data)})

    if result:
        print(f"[SUCCESS] Comment created")
        print("This should trigger doc_update events")
        print("Check subscriber terminal for events")
        return True

    return False


def test_publish_realtime():
    """Publish a custom event via publish_realtime."""
    print("Publishing custom event via publish_realtime...")

    timestamp = datetime.now().strftime("%H:%M:%S")

    # Try different publish methods
    endpoints = [
        'frappe.realtime.publish_realtime',
        'frappe.publish_realtime',
    ]

    for endpoint in endpoints:
        print(f"Trying endpoint: {endpoint}")
        result = api_call('POST', endpoint, {
            'event': 'msgprint',
            'message': json.dumps({
                'message': f'Test message at {timestamp}',
                'indicator': 'green',
                'title': 'Socket Test'
            }),
            'user': USER_EMAIL
        })

        if result:
            print(f"[SUCCESS] Event published via {endpoint}")
            print("Check subscriber terminal for msgprint event")
            return True

    return False


def test_get_user_info():
    """Test the authentication endpoint your socket server uses."""
    print("Testing frappe.realtime.get_user_info (used by socket auth)...")

    result = api_call('GET', 'frappe.realtime.get_user_info')

    if result:
        message = result.get('message', {})
        print(f"[SUCCESS] User info retrieved:")
        print(f"  User: {message.get('user', 'N/A')}")
        print(f"  User Type: {message.get('user_type', 'N/A')}")
        print(f"  Installed Apps: {message.get('installed_apps', [])}")
        return True

    return False


def main():
    print("Choose test method:")
    print("1. Test socket ping/pong (verify socket connectivity)")
    print("2. Test API ping (verify API connectivity)")
    print("3. Test get_user_info (verify auth endpoint)")
    print("4. Create ToDo item (triggers doc_update, list_update)")
    print("5. Update user bio (triggers doc_update)")
    print("6. Create Comment (triggers doc_update)")
    print("7. Publish realtime event (triggers custom event)")
    print("8. Run all tests")
    print()

    choice = input("Enter choice (1-8): ").strip()
    print()
    print("-" * 50)

    if choice == '1':
        test_socket_ping()
    elif choice == '2':
        test_api_ping()
    elif choice == '3':
        test_get_user_info()
    elif choice == '4':
        test_create_todo()
    elif choice == '5':
        test_update_user_settings()
    elif choice == '6':
        test_create_comment()
    elif choice == '7':
        test_publish_realtime()
    elif choice == '8':
        print("Running all tests...")
        print()
        tests = [
            ("API Ping", test_api_ping),
            ("Get User Info", test_get_user_info),
            ("Socket Ping", test_socket_ping),
            ("Create ToDo", test_create_todo),
            ("Update User", test_update_user_settings),
            ("Create Comment", test_create_comment),
            ("Publish Realtime", test_publish_realtime),
        ]
        for name, test_fn in tests:
            print(f"\n{'='*50}")
            print(f"TEST: {name}")
            print('='*50)
            test_fn()
            print()
    else:
        print("Invalid choice")


if __name__ == "__main__":
    main()
