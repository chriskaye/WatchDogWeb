"""
Manual/interactive smoke test for WatchDogWeb's API. Mirrors the style of the original
script (paste verification tokens from container logs) but updated for everything built
since: user_verification_tokens, site roles, provisioning, alert rules (incl. boolean),
lock/suspend, GDPR self-delete.

Run with the api container's logs visible (docker compose logs -f api) so you can copy
the [DEBUG] verification links/tokens it prints.

NOTE: device_registry rows are only ever created by the manufacturing process — there's
no API endpoint for it (deliberately; that's factory data, not something an org admin
should be able to fabricate). This test seeds a fake registry row directly via psycopg2
to simulate "a device came off the production line", which is a test-only shortcut, not
something the real frontend would ever do.
"""

import os
import requests
import psycopg2

BASE = "http://localhost:8000"


def pp(title, data):
    print(f"\n=== {title} ===")
    print(data)


def seed_fake_device_registry(serial_number: str, device_type: str):
    """Test-only: bypass the API to simulate a manufactured device already in the registry."""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "example"),
        dbname=os.getenv("DB_NAME", "postgres"),
    )
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO device_registry (serial_number, device_type, model)
        VALUES (%s, %s, %s)
        ON CONFLICT (serial_number) DO NOTHING;
        """,
        (serial_number, device_type, "test-model"),
    )
    conn.commit()
    cur.close()
    conn.close()
    pp("Seeded device_registry (test-only shortcut)", {"serial_number": serial_number, "device_type": device_type})


# ---------------------------
# Auth / verification
# ---------------------------
def register_owner(email, password):
    r = requests.post(f"{BASE}/users/register", json={"email": email, "password": password})
    pp("Register Owner", r.json())
    return r.json()["user_id"]


def verify_email(token):
    r = requests.get(f"{BASE}/verify", params={"token": token})
    pp("Verify Email", r.json())


def login(email, password):
    r = requests.post(f"{BASE}/token", data={"username": email, "password": password})
    pp("Login", r.json())
    return r.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------
# Sites / roles
# ---------------------------
def create_site(token, name):
    r = requests.post(f"{BASE}/sites", headers=auth_headers(token), json={"name": name})
    pp("Create Site", r.json())
    return r.json()["site_id"]


def invite_user(token, email, role, site_id=None, initial_password=None):
    r = requests.post(f"{BASE}/users/invite", headers=auth_headers(token),
                       json={"email": email, "role": role, "site_id": site_id, "initial_password": initial_password})
    pp("Invite User", r.json())
    return r.json().get("user_id")


# ---------------------------
# Provisioning
# ---------------------------
def provision_device(token, serial_number, site_id, name=None, node_template_id=None):
    r = requests.post(f"{BASE}/provisioning/activate", headers=auth_headers(token), json={
        "serial_number": serial_number, "site_id": site_id, "name": name,
        "node_template_id": node_template_id,
    })
    pp("Provision Device", r.json())
    return r.json()


# ---------------------------
# Alert rules
# ---------------------------
def create_numeric_alert_rule(token, serial_number, metric_name, tmin=None, tmax=None):
    r = requests.post(f"{BASE}/alert_rules", headers=auth_headers(token), json={
        "serial_number": serial_number, "metric_name": metric_name,
        "threshold_min": tmin, "threshold_max": tmax,
    })
    pp(f"Create Alert Rule ({metric_name})", r.json())
    return r.json()


def create_boolean_alert_rule(token, serial_number, metric_name, trigger_value):
    """e.g. metric_name='motion', trigger_value=True -> alert whenever motion is detected.
    Requires db_migration_002.sql (alert_rules.trigger_value) to have been applied."""
    r = requests.post(f"{BASE}/alert_rules", headers=auth_headers(token), json={
        "serial_number": serial_number, "metric_name": metric_name, "trigger_value": trigger_value,
    })
    pp(f"Create Boolean Alert Rule ({metric_name})", r.json())
    return r.json()


# ---------------------------
# Ingest
# ---------------------------
def ingest(gateway_id, sensor_id, temperature=None, humidity=None, motion=None, battery=None):
    r = requests.post(f"{BASE}/ingest", json={
        "gateway_id": gateway_id, "sensor_id": sensor_id,
        "temperature": temperature, "humidity": humidity, "motion": motion, "battery": battery,
    })
    pp("Ingest", r.json())


# ---------------------------
# Lock / Suspend / GDPR
# ---------------------------
def suspend_user(token, target_user_id, reason=None):
    r = requests.post(f"{BASE}/users/{target_user_id}/suspend", headers=auth_headers(token), json={"reason": reason})
    pp("Suspend User", r.json())


def request_self_delete(token):
    r = requests.post(f"{BASE}/users/me/self_delete/request", headers=auth_headers(token))
    pp("Request Self Delete", r.json())


# ---------------------------
# MAIN TEST FLOW
# ---------------------------
if __name__ == "__main__":
    owner_email = "owner@example.com"
    owner_pass = "secret123"

    owner_id = register_owner(owner_email, owner_pass)
    token = input("Enter verification token for owner (see api container logs): ")
    verify_email(token)
    owner_token = login(owner_email, owner_pass)

    site_id = create_site(owner_token, "Test Property")

    invited_pass = "invitedpass123"
    invited_id = invite_user(owner_token, "user2@example.com", "site_admin", site_id=site_id,
                              initial_password=invited_pass)
    invited_token_str = input("Enter verification token for invited user: ")
    verify_email(invited_token_str)  # response includes password_setup_required: False, since
                                      # the admin preset a password above
    user2_token = login("user2@example.com", invited_pass)

    seed_fake_device_registry("wdrt-a1b2c3", "gateway")
    seed_fake_device_registry("wdsn-d4e5f6", "sensor")

    provision_device(owner_token, "wdrt-a1b2c3", site_id, name="Root Node 1")
    provision_device(owner_token, "wdsn-d4e5f6", site_id, name="Sensor 1")

    create_numeric_alert_rule(owner_token, "wdsn-d4e5f6", "temperature", tmax=28.0)
    create_boolean_alert_rule(owner_token, "wdsn-d4e5f6", "motion", trigger_value=True)

    ingest("wdrt-a1b2c3", "wdsn-d4e5f6", temperature=30.5, motion=True, humidity=55.0, battery=3.7)

    request_self_delete(owner_token)