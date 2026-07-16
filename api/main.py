from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
import psycopg2
import os
import requests
import json

app = FastAPI()

# --- DB helper (simple sync) ---

def get_db():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "example"),
        dbname=os.getenv("DB_NAME", "postgres"),
    )
    return conn

# --- Pydantic models ---

class GatewayRegistration(BaseModel):
    gateway_id: str
    user_id: int | None = None
    name: str | None = None
    firmware_version: str | None = None
    crypto_id: int | None = None

class SensorCapability(BaseModel):
    capability_type: str
    unit: str

class SensorRegistration(BaseModel):
    sensor_id: str
    gateway_id: str
    name: str | None = None
    location: str | None = None
    firmware_version: str | None = None
    capabilities: list[SensorCapability] = []

class SoftDeleteGateway(BaseModel):
    gateway_id: str

class SoftDeleteSensor(BaseModel):
    sensor_id: str

class HardDeleteGateway(BaseModel):
    gateway_id: str

class GdprDeleteUser(BaseModel):
    user_id: int

class CryptoProfileCreate(BaseModel):
    user_id: int
    name: str
    mode: str      # 'psk' or 'certificate'
    key_id: str    # reference into secure store

class IngestPayload(BaseModel):
    gateway_id: str
    sensor_id: str
    temperature: float | None = None
    humidity: float | None = None
    motion: bool | None = None
    battery: float | None = None
    ts: str | None = None  # optional; DB will default to NOW() if missing

# --- Endpoints ---

@app.post("/ingest")
def ingest(data: IngestPayload):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sensor_data (
            gateway_id,
            sensor_id,
            temperature,
            humidity,
            motion,
            battery,
            ts
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            COALESCE(%s::timestamp, NOW())
        );
        """,
        (
            data.gateway_id,
            data.sensor_id,
            data.temperature,
            data.humidity,
            data.motion,
            data.battery,
            data.ts,
        ),
    )

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ingested", "gateway_id": data.gateway_id, "sensor_id": data.sensor_id}

@app.post("/crypto_profiles")
def create_crypto_profile(data: CryptoProfileCreate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO crypto_profiles (user_id, name, mode, key_id)
        VALUES (%s, %s, %s, %s)
        RETURNING crypto_id;
        """,
        (data.user_id, data.name, data.mode, data.key_id),
    )
    crypto_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"crypto_id": crypto_id}


@app.post("/gateways/register")
def register_gateway(data: GatewayRegistration):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gateways (gateway_id, user_id, name, firmware_version, crypto_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (gateway_id) DO UPDATE
        SET user_id = EXCLUDED.user_id,
            name = EXCLUDED.name,
            firmware_version = EXCLUDED.firmware_version,
            crypto_id = EXCLUDED.crypto_id;
        """,
        (data.gateway_id, data.user_id, data.name, data.firmware_version, data.crypto_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "gateway_registered", "gateway_id": data.gateway_id}


@app.post("/sensors/register")
def register_sensor(data: SensorRegistration):
    conn = get_db()
    cur = conn.cursor()

    # insert / update sensor
    cur.execute(
        """
        INSERT INTO sensors (sensor_id, gateway_id, name, location, firmware_version)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (sensor_id) DO UPDATE
        SET gateway_id = EXCLUDED.gateway_id,
            name = EXCLUDED.name,
            location = EXCLUDED.location,
            firmware_version = EXCLUDED.firmware_version;
        """,
        (data.sensor_id, data.gateway_id, data.name, data.location, data.firmware_version),
    )

    # clear existing capabilities
    cur.execute(
        "DELETE FROM sensor_capabilities WHERE sensor_id = %s;",
        (data.sensor_id,),
    )

    # insert new capabilities
    for cap in data.capabilities:
        cur.execute(
            """
            INSERT INTO sensor_capabilities (sensor_id, capability_type, unit)
            VALUES (%s, %s, %s);
            """,
            (data.sensor_id, cap.capability_type, cap.unit),
        )

    conn.commit()
    cur.close()
    conn.close()
    return {"status": "sensor_registered", "sensor_id": data.sensor_id}


@app.post("/gateways/soft_delete")
def soft_delete_gateway(data: SoftDeleteGateway):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE gateways SET is_active = FALSE WHERE gateway_id = %s;",
        (data.gateway_id,),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "gateway_soft_deleted", "gateway_id": data.gateway_id}


@app.post("/sensors/soft_delete")
def soft_delete_sensor(data: SoftDeleteSensor):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE sensors SET is_active = FALSE WHERE sensor_id = %s;",
        (data.sensor_id,),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "sensor_soft_deleted", "sensor_id": data.sensor_id}


@app.post("/gateways/hard_delete")
def hard_delete_gateway_endpoint(data: HardDeleteGateway):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT hard_delete_gateway(%s);", (data.gateway_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "gateway_hard_deleted", "gateway_id": data.gateway_id}


@app.post("/users/gdpr_delete")
def gdpr_delete_user(data: GdprDeleteUser):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT hard_delete_user(%s);", (data.user_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "user_deleted_gdpr", "user_id": data.user_id}
