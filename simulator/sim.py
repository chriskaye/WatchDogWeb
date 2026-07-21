import os
import time
import random
from datetime import datetime

import psycopg2
import requests

API_URL = "http://api:80/ingest"
ORG_ID = 1
SITE_NAME = "Headquarters"

# Matches the provisioning assumption in main.py: gateway_id/sensor_id == serial_number.
# "wdrt-" + 6 alphanumerics for a Root/Gateway node, "wdsn-" + 6 alphanumerics for a Sensor node.
GATEWAY_SERIAL = "wdrt-hq0001"

# The root/gateway node's own onboard sensors are modeled as a sensor node in its own
# right (device_type='sensor' in device_registry, sensors.gateway_id pointing at itself) —
# there's no separate "gateway has readings" concept in the schema, sensor_data rows always
# carry both a gateway_id and a sensor_id.
NODES = [
    {"sensor_serial": "wdsn-hq0000", "name": "Root Node", "location": "Gateway"},
    {"sensor_serial": "wdsn-office1", "name": "Office", "location": "Office"},
    {"sensor_serial": "wdsn-kitchen1", "name": "Kitchen", "location": "Kitchen"},
]

CAPABILITIES = [
    {"capability_type": "temperature", "unit": "°C"},
    {"capability_type": "humidity", "unit": "%"},
    {"capability_type": "battery_voltage", "unit": "V"},
]


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "example"),
        dbname=os.getenv("DB_NAME", "postgres"),
    )


def wait_for_db(retries=30, delay=2):
    for attempt in range(1, retries + 1):
        try:
            conn = get_db()
            conn.close()
            return
        except psycopg2.OperationalError as e:
            print(f"[sim] DB not ready yet (attempt {attempt}/{retries}): {e}")
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database after repeated retries")


def seed_fleet():
    """Idempotently creates the Headquarters site, one gateway, and three sensor nodes
    (the gateway's own onboard sensors plus Office and Kitchen) for ORG_ID, each with
    temperature/humidity/battery_voltage capabilities. Safe to run on every container
    start — every step is a lookup-or-insert, so re-running just confirms the fleet
    still exists rather than duplicating it."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM organisations WHERE org_id = %s;", (ORG_ID,))
    if not cur.fetchone():
        cur.close(); conn.close()
        raise RuntimeError(
            f"org_id={ORG_ID} doesn't exist yet. Bootstrap an organisation (and its first "
            f"user) before running the simulator — see the outstanding tasks doc."
        )

    cur.execute("SELECT site_id FROM sites WHERE org_id = %s AND name = %s;", (ORG_ID, SITE_NAME))
    row = cur.fetchone()
    if row:
        site_id = row[0]
    else:
        cur.execute(
            "INSERT INTO sites (org_id, name) VALUES (%s, %s) RETURNING site_id;",
            (ORG_ID, SITE_NAME),
        )
        site_id = cur.fetchone()[0]
        print(f"[sim] Created site '{SITE_NAME}' (site_id={site_id}) for org_id={ORG_ID}")

    # Gateway — device_registry first (gateways.serial_number has an FK to it), then the
    # gateway itself.
    cur.execute(
        """
        INSERT INTO device_registry (serial_number, device_type, model, is_provisioned, provisioned_at)
        VALUES (%s, 'gateway', %s, TRUE, NOW())
        ON CONFLICT (serial_number) DO UPDATE SET is_provisioned = TRUE, provisioned_at = COALESCE(device_registry.provisioned_at, NOW());
        """,
        (GATEWAY_SERIAL, "WatchDog Root Node"),
    )
    cur.execute(
        """
        INSERT INTO gateways (gateway_id, org_id, site_id, serial_number, name, is_active)
        VALUES (%s, %s, %s, %s, %s, TRUE)
        ON CONFLICT (gateway_id) DO UPDATE
        SET org_id = EXCLUDED.org_id, site_id = EXCLUDED.site_id, name = EXCLUDED.name, is_active = TRUE;
        """,
        (GATEWAY_SERIAL, ORG_ID, site_id, GATEWAY_SERIAL, f"{SITE_NAME} Gateway"),
    )

    for node in NODES:
        serial = node["sensor_serial"]
        cur.execute(
            """
            INSERT INTO device_registry (serial_number, device_type, model, is_provisioned, provisioned_at)
            VALUES (%s, 'sensor', %s, TRUE, NOW())
            ON CONFLICT (serial_number) DO UPDATE SET is_provisioned = TRUE, provisioned_at = COALESCE(device_registry.provisioned_at, NOW());
            """,
            (serial, node["name"]),
        )
        cur.execute(
            """
            INSERT INTO sensors (sensor_id, gateway_id, org_id, site_id, serial_number, name, location, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (sensor_id) DO UPDATE
            SET gateway_id = EXCLUDED.gateway_id, org_id = EXCLUDED.org_id, site_id = EXCLUDED.site_id,
                name = EXCLUDED.name, location = EXCLUDED.location, is_active = TRUE;
            """,
            (serial, GATEWAY_SERIAL, ORG_ID, site_id, serial, node["name"], node["location"]),
        )
        cur.execute("DELETE FROM sensor_capabilities WHERE sensor_id = %s;", (serial,))
        for cap in CAPABILITIES:
            cur.execute(
                "INSERT INTO sensor_capabilities (sensor_id, capability_type, unit) VALUES (%s, %s, %s);",
                (serial, cap["capability_type"], cap["unit"]),
            )
        print(f"[sim] Provisioned sensor '{node['name']}' ({serial}) with temperature/humidity/battery_voltage")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[sim] Fleet ready: gateway={GATEWAY_SERIAL}, sensors={[n['sensor_serial'] for n in NODES]}")


def generate_payload(sensor_serial):
    return {
        "gateway_id": GATEWAY_SERIAL,
        "sensor_id": sensor_serial,
        "temperature": round(random.uniform(18, 25), 2),
        "humidity": round(random.uniform(40, 60), 2),
        "battery": round(random.uniform(3.2, 4.1), 2),
        "timestamp": datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":
    wait_for_db()
    seed_fleet()
    print(f"[sim] Simulating gateway={GATEWAY_SERIAL} with sensors {[n['sensor_serial'] for n in NODES]}")
    while True:
        for node in NODES:
            payload = generate_payload(node["sensor_serial"])
            try:
                r = requests.post(API_URL, json=payload)
                print(f"[sim] Sent ({node['name']}):", payload, "Status:", r.status_code)
            except Exception as e:
                print(f"[sim] Error sending payload for {node['name']}:", e)
        time.sleep(60)
