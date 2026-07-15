from fastapi import FastAPI
from pydantic import BaseModel
import psycopg2

app = FastAPI()

class SensorPayload(BaseModel):
    gateway_id: str
    sensor_id: str
    temperature: float
    humidity: float
    motion: bool
    battery: float
    timestamp: str

def get_conn():
    return psycopg2.connect(
        dbname="postgres",
        user="postgres",
        password="example",
        host="db"
    )

@app.on_event("startup")
def startup():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensor_data (
            id SERIAL PRIMARY KEY,
            gateway_id TEXT,
            sensor_id TEXT,
            temperature DOUBLE PRECISION,
            humidity DOUBLE PRECISION,
            motion BOOLEAN,
            battery DOUBLE PRECISION,
            ts TIMESTAMPTZ
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.post("/ingest")
def ingest(payload: SensorPayload):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sensor_data (gateway_id, sensor_id, temperature, humidity, motion, battery, ts)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        payload.gateway_id,
        payload.sensor_id,
        payload.temperature,
        payload.humidity,
        payload.motion,
        payload.battery,
        payload.timestamp
    ))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}
