import time
import random
import string
from datetime import datetime
import requests

API_URL = "http://api:80/ingest"

# Matches the provisioning assumption in main.py: gateway_id/sensor_id == serial_number.
# Format per your spec: "wdrt-" + 6 alphanumerics for a Root/Gateway node,
# "wdsn-" + 6 alphanumerics for a Sensor node.
ROOT_SERIAL = "wdrt-a1b2c3"
SENSOR_SERIAL = "wdsn-d4e5f6"


def generate_payload():
    return {
        "gateway_id": ROOT_SERIAL,
        "sensor_id": SENSOR_SERIAL,
        "temperature": round(random.uniform(18, 25), 2),
        "humidity": round(random.uniform(40, 60), 2),
        "motion": random.choice([True, False]),
        "battery": round(random.uniform(3.2, 4.1), 2),
        "timestamp": datetime.utcnow().isoformat()
    }


if __name__ == "__main__":
    print(f"[sim] Simulating root={ROOT_SERIAL} sensor={SENSOR_SERIAL}")
    print("[sim] NOTE: these serials must already be provisioned via /provisioning/activate "
          "(and exist in device_registry) or /ingest will just silently fail to resolve a "
          "serial_number for alert evaluation -- sensor_data will still be recorded either way.")
    while True:
        payload = generate_payload()
        try:
            r = requests.post(API_URL, json=payload)
            print("Sent:", payload, "Status:", r.status_code)
        except Exception as e:
            print("Error sending payload:", e)
        time.sleep(60)