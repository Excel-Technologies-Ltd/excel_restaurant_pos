"""
Socket.IO Test Subscriber
Run this file first to listen for Frappe realtime events.
"""
import socketio
import os
from datetime import datetime

# Configuration
BASE_URL = os.getenv("SOCKET_URL", "https://arcpos.aninda.me")
SITE_NAME = os.getenv("SITE_NAME", "arcpos.aninda.me")
BEARER_TOKEN = os.getenv("BEARER_TOKEN", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYXptaW5AZXhjZWxiZC5jb20iLCJleHAiOjE3NzAwMzY4MzEsImlhdCI6MTc3MDAzMzIzMSwidHlwZSI6ImFjY2VzcyJ9.DXZQU5KkhanRSGCZobkj0xBsbAyrAONxY025voRGbUg")
USER_EMAIL = os.getenv("USER_EMAIL", "azmin@excelbd.com")

NAMESPACE = f"/{SITE_NAME}"
VERBOSE = os.getenv("VERBOSE", "0") == "1"

print("=" * 60)
print("Socket.IO Test Subscriber - Frappe Events")
print("=" * 60)
print(f"URL: {BASE_URL}")
print(f"Namespace: {NAMESPACE}")
print(f"User: {USER_EMAIL}")
print("=" * 60)
print()

sio = socketio.Client(logger=VERBOSE, engineio_logger=VERBOSE)
event_count = 0


def log_event(event_name, data):
    global event_count
    event_count += 1
    timestamp = datetime.now().strftime("%H:%M:%S")
    print()
    print(f"[{timestamp}] EVENT #{event_count}: {event_name}")
    print("-" * 50)
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"  {key}: {value}")
    else:
        print(f"  Data: {data}")
    print("-" * 50)


# Use decorator-based event handlers with explicit namespace
@sio.on('connect', namespace=NAMESPACE)
def on_connect():
    print()
    print("[CONNECTED] Socket connected successfully!")
    print(f"Session ID: {sio.sid}")
    print()

    # Frappe room format: {site}:{type}:{value}
    # Examples:
    #   arcpos.aninda.me:user:azmin@excelbd.com
    #   arcpos.aninda.me:doctype:Sales Invoice
    #   arcpos.aninda.me:doc:Sales Invoice/ORD-26-00620

    # Join user-specific room (for user notifications)
    user_room = f"{SITE_NAME}:user:{USER_EMAIL}"
    print(f"Joining room: {user_room}")
    sio.emit("room:join", user_room, namespace=NAMESPACE)

    # Join doctype rooms to receive list_update events
    doctypes_to_watch = ["Sales Invoice", "POS Invoice", "ToDo"]
    for doctype in doctypes_to_watch:
        doctype_room = f"{SITE_NAME}:doctype:{doctype}"
        print(f"Joining room: {doctype_room}")
        sio.emit("room:join", doctype_room, namespace=NAMESPACE)

    print()
    print("Waiting for Frappe events...")
    print("Press Ctrl+C to disconnect")
    print()


@sio.on('connect_error', namespace=NAMESPACE)
def on_connect_error(data):
    print(f"[ERROR] Connection failed: {data}")


@sio.on('disconnect', namespace=NAMESPACE)
def on_disconnect():
    print(f"[DISCONNECTED] Total events received: {event_count}")


# Room confirmations
@sio.on('room:joined', namespace=NAMESPACE)
def on_room_joined(data):
    print(f"[ROOM] Joined: {data}")


@sio.on('room:left', namespace=NAMESPACE)
def on_room_left(data):
    print(f"[ROOM] Left: {data}")


# Frappe document events
@sio.on('doc_update', namespace=NAMESPACE)
def on_doc_update(data):
    log_event("doc_update", data)


@sio.on('list_update', namespace=NAMESPACE)
def on_list_update(data):
    log_event("list_update", data)


# Notification events
@sio.on('new_notification', namespace=NAMESPACE)
def on_new_notification(data):
    log_event("new_notification", data)


@sio.on('notification', namespace=NAMESPACE)
def on_notification(data):
    log_event("notification", data)


# Message events
@sio.on('msgprint', namespace=NAMESPACE)
def on_msgprint(data):
    log_event("msgprint", data)


@sio.on('eval_js', namespace=NAMESPACE)
def on_eval_js(data):
    log_event("eval_js", data)


@sio.on('progress', namespace=NAMESPACE)
def on_progress(data):
    log_event("progress", data)


@sio.on('pong', namespace=NAMESPACE)
def on_pong(data):
    log_event("pong", data)


# Catch-all for any other event
@sio.on('*', namespace=NAMESPACE)
def catch_all(event, data):
    log_event(f"OTHER:{event}", data)


if __name__ == "__main__":
    try:
        headers = {
            'Authorization': f'Bearer {BEARER_TOKEN}',
            'X-Frappe-Site-Name': SITE_NAME,
            'Origin': BASE_URL,
        }

        print(f"Connecting to {BASE_URL} namespace {NAMESPACE}...")
        print()

        sio.connect(
            BASE_URL,
            namespaces=[NAMESPACE],
            transports=['polling', 'websocket'],
            socketio_path='/socket.io',
            headers=headers,
            wait_timeout=10
        )

        sio.wait()

    except socketio.exceptions.ConnectionError as e:
        print(f"\n[CONNECTION ERROR] {e}")
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sio.disconnect()
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
