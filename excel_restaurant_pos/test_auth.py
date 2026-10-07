#!/usr/bin/env python3
"""
Quick test script to verify JWT authentication endpoint
"""
import requests
import json

# Configuration
BASE_URL = "https://arcpos.aninda.me"
SITE_NAME = "arcpos.aninda.me"
USERNAME = "azmin@excelbd.com"
PASSWORD = "Azmin@123#"

print("=" * 60)
print("JWT Authentication Test")
print("=" * 60)
print(f"URL: {BASE_URL}")
print(f"Site: {SITE_NAME}")
print(f"User: {USERNAME}")
print("")

# Test 1: Login and get JWT token
print("Test 1: Login and get JWT token")
print("-" * 60)

auth_endpoint = f"{BASE_URL}/api/method/excel_restaurant_pos.api.auth.login.login"
headers = {
    "X-Frappe-Site-Name": SITE_NAME,
    "Content-Type": "application/json"
}
auth_data = {
    "user": USERNAME,
    "pwd": PASSWORD
}

try:
    print(f"Calling: POST {auth_endpoint}")
    response = requests.post(auth_endpoint, json=auth_data, headers=headers)

    print(f"Status Code: {response.status_code}")
    print("")

    if response.status_code == 200:
        data = response.json()
        print("✅ Login successful!")
        print("")

        # Pretty print response
        print("Response structure:")
        print(json.dumps(data, indent=2)[:500] + "...")
        print("")

        # Extract token
        message = data.get("message", {})
        if isinstance(message, dict):
            data_obj = message.get("data", {})
            if isinstance(data_obj, dict):
                access_token = data_obj.get("access_token")
                refresh_token = data_obj.get("refresh_token")
                user_info = data_obj.get("user", {})

                if access_token:
                    print("✅ Got access token!")
                    print(f"   Token (first 40 chars): {access_token[:40]}...")
                    print(f"   Token length: {len(access_token)} characters")
                    print("")

                    if refresh_token:
                        print("✅ Got refresh token!")
                        print(f"   Token (first 40 chars): {refresh_token[:40]}...")
                        print("")

                    if user_info:
                        print("User Info:")
                        print(f"   Name: {user_info.get('full_name')}")
                        print(f"   Email: {user_info.get('email')}")
                        print("")

                    # Test 2: Verify token by calling a protected endpoint
                    print("Test 2: Verify token works")
                    print("-" * 60)

                    verify_endpoint = f"{BASE_URL}/api/method/frappe.realtime.get_user_info"
                    verify_headers = {
                        "Authorization": f"Bearer {access_token}",
                        "X-Frappe-Site-Name": SITE_NAME
                    }

                    print(f"Calling: GET {verify_endpoint}")
                    verify_response = requests.get(verify_endpoint, headers=verify_headers)
                    print(f"Status Code: {verify_response.status_code}")
                    print("")

                    if verify_response.status_code == 200:
                        print("✅ Token verification successful!")
                        verify_data = verify_response.json()
                        print(json.dumps(verify_data, indent=2))
                        print("")
                        print("=" * 60)
                        print("✅ ALL TESTS PASSED!")
                        print("=" * 60)
                        print("")
                        print("Your Socket.IO client should work with Bearer token authentication.")
                        print("Run: python socket_client.py")
                    else:
                        print(f"❌ Token verification failed: {verify_response.text}")
                else:
                    print("❌ No access_token found in response!")
                    print("Response structure:")
                    print(json.dumps(data, indent=2))
    else:
        print(f"❌ Login failed!")
        print(f"Response: {response.text}")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("")
print("=" * 60)
