import time
import random
import requests
from datetime import datetime

API_URL = "http://api:80/ingest" #"http://localhost:8000/ingest" 

def generate_payload():
    return {
        "gateway_id": "gw1",
        "sensor_id": "room1",
        "temperature": round(random.uniform(18, 25), 2),
        "humidity": round(random.uniform(40, 60), 2),
        "motion": random.choice([True, False]),
        "battery": round(random.uniform(3.2, 4.1), 2),
        "timestamp": datetime.utcnow().isoformat()
    }

while True:
    payload = generate_payload()
    try:
        r = requests.post(API_URL, json=payload)
        print("Sent:", payload, "Status:", r.status_code)
    except Exception as e:
        print("Error sending payload:", e)
    time.sleep(60)
