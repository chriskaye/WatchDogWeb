import psycopg2
import os

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "example"),
        dbname=os.getenv("DB_NAME", "postgres"),
    )

def get_sensors_and_capabilities_for_gateway(gateway_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT s.sensor_id, c.capability_type, c.unit
        FROM sensors s
        LEFT JOIN sensor_capabilities c ON s.sensor_id = c.sensor_id
        WHERE s.gateway_id = %s AND s.is_active = TRUE;
    """, (gateway_id,))

    rows = cur.fetchall()
    conn.close()

    sensors = {}
    for sensor_id, cap_type, unit in rows:
        sensors.setdefault(sensor_id, [])
        if cap_type:
            sensors[sensor_id].append({
                "capability_type": cap_type,
                "unit": unit
            })

    return sensors
