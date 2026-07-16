import requests
import json
import os

GRAFANA_URL = os.getenv("GRAFANA_URL", "http://grafana:3000")
GRAFANA_API_KEY = os.getenv("GRAFANA_API_KEY", "glsa_nOneYXgwKtHiptsOcCcDDL0ae1p3sFpN_5aecf2c0")

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {GRAFANA_API_KEY}"
}

def grafana_post(path, payload):
    url = f"{GRAFANA_URL}{path}"
    r = requests.post(url, headers=headers, data=json.dumps(payload))
    print("Grafana POST", path, r.status_code, r.text)
    return r

def build_panel(sensor_id, capability, y):
    metric = capability["capability_type"]
    unit = capability["unit"]

    return {
        "type": "timeseries",
        "title": f"{sensor_id} — {metric}",
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 8},
        "targets": [
            {
                "datasource": {"type": "postgres", "uid": "timescaledb"},
                "format": "time_series",
                "rawSql": f"""
                    SELECT ts AS time, {metric}
                    FROM sensor_data
                    WHERE sensor_id = '{sensor_id}'
                    ORDER BY ts;
                """
            }
        ],
        "fieldConfig": {
            "defaults": {
                "unit": unit
            }
        }
    }

def create_dashboard(gateway_id, sensors_with_caps):
    panels = []
    y = 0

    for sensor_id, capabilities in sensors_with_caps.items():

        # collapsible row
        panels.append({
            "type": "row",
            "title": f"{sensor_id} Panels",
            "collapsed": True,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}
        })
        y += 1

        # panels for each capability
        for cap in capabilities:
            panels.append(build_panel(sensor_id, cap, y))
            y += 8

    dashboard = {
        "dashboard": {
            "id": None,
            "uid": f"gw-{gateway_id}",
            "title": f"Gateway {gateway_id} Dashboard",
            "panels": panels
        },
        "overwrite": True
    }

    return grafana_post("/api/dashboards/db", dashboard)
