import requests
import time

BASE = "http://localhost:8000"   # adjust if needed

def pp(title, data):
    print(f"\n=== {title} ===")
    print(data)


# ---------------------------
# 1. Register first user (owner)
# ---------------------------
def register_owner(email, password):
    r = requests.post(f"{BASE}/users/register", json={
        "email": email,
        "password": password
    })
    pp("Register Owner", r.json())
    return r.json()["user_id"]


# ---------------------------
# 2. Verify email
# ---------------------------
def verify_email(token):
    r = requests.get(f"{BASE}/verify", params={"token": token})
    pp("Verify Email", r.json())


# ---------------------------
# 3. Login
# ---------------------------
def login(email, password):
    r = requests.post(f"{BASE}/token", data={
        "username": email,
        "password": password
    })
    pp("Login", r.json())
    return r.json()["access_token"]


# ---------------------------
# 4. Invite user
# ---------------------------
def invite_user(token, email, role):
    r = requests.post(
        f"{BASE}/users/invite",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": email, "role": role}
    )
    pp("Invite User", r.json())
    return r.json()["user_id"]


# ---------------------------
# 5. List auth methods
# ---------------------------
def list_auth_methods(token):
    r = requests.get(
        f"{BASE}/users/me/auth-methods",
        headers={"Authorization": f"Bearer {token}"}
    )
    pp("Auth Methods", r.json())


# ---------------------------
# 6. Link SSO (stub)
# ---------------------------
def link_sso(token, provider):
    r = requests.post(
        f"{BASE}/users/me/link-sso",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": provider, "code": "dummy"}
    )
    pp("Link SSO", r.json())


# ---------------------------
# 7. Register gateway
# ---------------------------
def register_gateway(token, gateway_id):
    r = requests.post(
        f"{BASE}/gateways/register",
        headers={"Authorization": f"Bearer {token}"},
        json={"gateway_id": gateway_id}
    )
    pp("Register Gateway", r.json())


# ---------------------------
# 8. Register sensor
# ---------------------------
def register_sensor(token, sensor_id, gateway_id):
    r = requests.post(
        f"{BASE}/sensors/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sensor_id": sensor_id,
            "gateway_id": gateway_id,
            "name": "Test Sensor",
            "location": "Lab",
            "firmware_version": "1.0.0",
            "capabilities": [
                {"capability_type": "temperature", "unit": "C"},
                {"capability_type": "humidity", "unit": "%"}
            ]
        }
    )
    pp("Register Sensor", r.json())


# ---------------------------
# 9. Ingest data
# ---------------------------
def ingest(gateway_id, sensor_id):
    r = requests.post(
        f"{BASE}/ingest",
        json={
            "gateway_id": gateway_id,
            "sensor_id": sensor_id,
            "temperature": 22.5,
            "humidity": 55.0,
            "battery": 3.7
        }
    )
    pp("Ingest", r.json())


# ---------------------------
# 10. Create OTA job
# ---------------------------
def create_ota(token, target_type, target_id, fw):
    r = requests.post(
        f"{BASE}/ota/jobs/create",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": target_type,
            "target_id": target_id,
            "firmware_version": fw
        }
    )
    pp("Create OTA Job", r.json())
    return r.json()["ota_id"]


# ---------------------------
# 11. Poll OTA jobs
# ---------------------------
def poll_ota(gateway_id):
    r = requests.get(f"{BASE}/ota/jobs/pending", params={"gateway_id": gateway_id})
    pp("Poll OTA Jobs", r.json())


# ---------------------------
# 12. Update OTA job
# ---------------------------
def update_ota(ota_id, status):
    r = requests.post(
        f"{BASE}/ota/jobs/update",
        json={"ota_id": ota_id, "status": status}
    )
    pp("Update OTA Job", r.json())


# ---------------------------
# MAIN TEST FLOW
# ---------------------------
if __name__ == "__main__":
    owner_email = "owner@example.com"
    owner_pass = "secret123"

    # 1. Register owner
    owner_id = register_owner(owner_email, owner_pass)

    # You must manually copy the verification token from your logs
    token = input("Enter verification token for owner: ")
    verify_email(token)

    # 3. Login owner
    owner_token = login(owner_email, owner_pass)

    # 4. Invite second user
    invited_id = invite_user(owner_token, "user2@example.com", "viewer")

    invited_token = input("Enter verification token for invited user: ")
    verify_email(invited_token)

    user2_token = login("user2@example.com", owner_pass)

    # 5. List auth methods
    list_auth_methods(owner_token)

    # 6. Link SSO
    link_sso(owner_token, "google")

    # 7. Register gateway
    register_gateway(owner_token, "gw-001")

    # 8. Register sensor
    register_sensor(owner_token, "sensor-001", "gw-001")

    # 9. Ingest
    ingest("gw-001", "sensor-001")

    # 10. Create OTA job
    ota_id = create_ota(owner_token, "sensor", "sensor-001", "2.0.0")

    # 11. Poll OTA jobs
    poll_ota("gw-001")

    # 12. Update OTA job
    update_ota(ota_id, "success")
