import requests
import json

GRAFANA_URL = "http://grafana:3000"
API_KEY = "glsa_nOneYXgwKtHiptsOcCcDDL0ae1p3sFpN_5aecf2c0"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

def create_dashboard(gateway_id, sensors):
    panels = []
    y = 0

    # Last readings table
    panels.append({
        "type": "table",
        "title": f"Gateway {gateway_id} - Last Readings",
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 8},
        "targets": [{
            "rawSql": """
                SELECT sensor_id, temperature, humidity, motion, battery, ts
                FROM sensor_data
                WHERE gateway_id = '%s'
                ORDER BY ts DESC
                LIMIT 20;
            """ % gateway_id,
            "format": "table"
        }]
    })
    y += 8

    # Panels per sensor
    for sensor_id in sensors:
        for metric in ["temperature", "humidity", "battery"]:
            panels.append({
                "type": "timeseries",
                "title": f"{sensor_id} - {metric}",
                "gridPos": {"x": 0, "y": y, "w": 24, "h": 8},
                "targets": [{
                    "rawSql": """
                        SELECT ts AS time, %s
                        FROM sensor_data
                        WHERE sensor_id = '%s'
                        ORDER BY ts;
                    """ % (metric, sensor_id),
                    "format": "time_series"
                }]
            })
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

    r = requests.post(
        f"{GRAFANA_URL}/api/dashboards/db",
        headers=headers,
        data=json.dumps(dashboard)
    )

    return r.json()
