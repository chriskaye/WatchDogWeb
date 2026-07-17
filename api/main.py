from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel
import psycopg2
from datetime import datetime, timedelta
import uuid
import os
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
import requests
import json
from grafana import create_dashboard
from db_helpers import get_sensors_and_capabilities_for_gateway

app = FastAPI()

# --- Auth setup ---
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:8501")
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_THIS_SECRET")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

#pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# SSO env vars (can be empty for now)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")

MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
MICROSOFT_REDIRECT_URI = os.getenv("MICROSOFT_REDIRECT_URI", "")

X_CLIENT_ID = os.getenv("X_CLIENT_ID", "")
X_CLIENT_SECRET = os.getenv("X_CLIENT_SECRET", "")
X_REDIRECT_URI = os.getenv("X_REDIRECT_URI", "")

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

class User(BaseModel):
    user_id: int
    email: str
    org_id: int
    role: str
    is_verified: bool

class UserCreate(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class InviteUser(BaseModel):
    email: str
    role: str  # 'admin' or 'viewer'

class LinkSSO(BaseModel):
    provider: str  # 'google', 'microsoft', 'x'
    code: str      # OAuth code from provider

class UnlinkMethod(BaseModel):
    method_type: str  # 'password', 'google', 'microsoft', 'x'

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

class OtaJobCreate(BaseModel):
    target_type: str      # 'gateway' or 'sensor'
    target_id: str        # gateway_id or sensor_id
    firmware_version: str

class OtaJobUpdate(BaseModel):
    ota_id: int
    status: str           # 'in_progress','success','failed'
    error_message: str | None = None

# --- Auth Helpers ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )

def get_password_hash(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- User lookup and current user dependency

def get_user_by_email(email: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, email, org_id, role, is_verified, password_hash FROM users WHERE email = %s;",
        (email,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    user_id, email, org_id, role, is_verified, password_hash = row
    return User(user_id=user_id, email=email, org_id=org_id, role=role, is_verified=is_verified), password_hash

def get_user_by_id(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, email, org_id, role, is_verified FROM users WHERE user_id = %s;",
        (user_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    uid, email, org_id, role, is_verified = row
    return User(user_id=uid, email=email, org_id=org_id, role=role, is_verified=is_verified)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_id(user_id)
    if user is None:
        raise credentials_exception
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return user

def require_role(user: User, allowed: list[str]):
    if user.role not in allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

# --- Sending Email stub

def send_verification_email(email: str, token: str):
    verify_url = f"https://yourdomain.com/verify?token={token}"
    # Replace this with real email sending later
    print(f"[DEBUG] Send verification email to {email}: {verify_url}")

# --- create organisations and unverified users

def create_org_and_owner(email: str, password_hash: str | None, provider: str | None, sub: str | None):
    token = str(uuid.uuid4())
    expires = datetime.utcnow() + timedelta(hours=24)

    conn = get_db()
    cur = conn.cursor()

    # create organisation
    cur.execute(
        "INSERT INTO organisations (name) VALUES (%s) RETURNING org_id;",
        (f"{email}'s Organisation",)
    )
    org_id = cur.fetchone()[0]

    # create user as owner
    cur.execute(
        """
        INSERT INTO users (email, password_hash, social_provider, social_sub,
                           is_verified, verification_token, verification_expires,
                           org_id, role)
        VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s, 'owner')
        RETURNING user_id;
        """,
        (email, password_hash, provider, sub, token, expires, org_id),
    )
    user_id = cur.fetchone()[0]

    # add auth method if password
    if password_hash:
        cur.execute(
            "INSERT INTO user_auth_methods (user_id, method_type) VALUES (%s, %s);",
            (user_id, "password"),
        )

    conn.commit()
    cur.close()
    conn.close()

    send_verification_email(email, token)
    return user_id

def create_unverified_user_in_org(email: str, org_id: int, role: str):
    token = str(uuid.uuid4())
    expires = datetime.utcnow() + timedelta(hours=24)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (email, is_verified, verification_token, verification_expires,
                           org_id, role)
        VALUES (%s, FALSE, %s, %s, %s, %s)
        RETURNING user_id;
        """,
        (email, token, expires, org_id, role),
    )
    user_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    send_verification_email(email, token)
    return user_id

# --- Endpoints ---

@app.post("/users/register") #first user in org become admin
def register_user(data: UserCreate):
    # check if email exists
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE email = %s;", (data.email,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = get_password_hash(data.password)
    user_id = create_org_and_owner(data.email, hashed, None, None)
    return {"user_id": user_id, "email": data.email}

@app.post("/token", response_model=Token) # JWT login
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    result = get_user_by_email(form_data.username)
    if not result:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    user, password_hash = result

    if not password_hash or not verify_password(form_data.password, password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")

    access_token = create_access_token(data={"sub": user.user_id})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/verify") # process email varification links
def verify_email(token: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, verification_expires
        FROM users
        WHERE verification_token = %s AND is_verified = FALSE;
        """,
        (token,),
    )
    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or already used token")

    user_id, expires = row

    if datetime.utcnow() > expires:
        cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Verification expired. Please register again.")

    cur.execute(
        """
        UPDATE users
        SET is_verified = TRUE,
            verification_token = NULL,
            verification_expires = NULL
        WHERE user_id = %s;
        """,
        (user_id,),
    )
    conn.commit()
    cur.close()
    conn.close()

    return {"status": "verified"}

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

@app.post("/users/invite") # users invited by org admins
def invite_user(data: InviteUser, current_user: User = Depends(get_current_user)):
    require_role(current_user, ["owner", "admin"])

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE email = %s;", (data.email,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        raise HTTPException(status_code=400, detail="User already exists")

    if data.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")

    user_id = create_unverified_user_in_org(data.email, current_user.org_id, data.role)
    return {"status": "invited", "user_id": user_id}

# add this endpoint, e.g. near list_auth_methods
@app.get("/users/me", response_model=User)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/users/me/auth-methods") # list log-in methods for logged-in user
def list_auth_methods(current_user: User = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT method_type, provider_sub FROM user_auth_methods WHERE user_id = %s;",
        (current_user.user_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    methods = [
        {"method_type": mtype, "provider_sub": sub}
        for mtype, sub in rows
    ]
    return {"methods": methods}

def ensure_email_not_taken(email: str, user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE email = %s;", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row[0] != user_id:
        raise HTTPException(status_code=400, detail="Email already associated with another account")

def ensure_provider_sub_unique(provider: str, sub: str, user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id FROM user_auth_methods WHERE method_type = %s AND provider_sub = %s;",
        (provider, sub),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row[0] != user_id:
        raise HTTPException(status_code=400, detail="SSO identity already associated with another account")

@app.post("/users/me/link-sso") # links SSO methods for a user
def link_sso(data: LinkSSO, current_user: User = Depends(get_current_user)):
    provider = data.provider

    # Here you would exchange data.code for tokens and get provider_sub + email
    # For now, we stub provider_sub and email
    provider_sub = f"stub-{provider}-sub"
    email = current_user.email  # assume same email

    ensure_email_not_taken(email, current_user.user_id)
    ensure_provider_sub_unique(provider, provider_sub, current_user.user_id)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_auth_methods (user_id, method_type, provider_sub)
        VALUES (%s, %s, %s);
        """,
        (current_user.user_id, provider, provider_sub),
    )
    conn.commit()
    cur.close()
    conn.close()

    return {"status": "linked", "provider": provider}

@app.post("/users/me/unlink-method") # unlink an SSO method for user
def unlink_method(data: UnlinkMethod, current_user: User = Depends(get_current_user)):
    method_type = data.method_type

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM user_auth_methods WHERE user_id = %s;",
        (current_user.user_id,),
    )
    count = cur.fetchone()[0]

    if count <= 1:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot remove last login method")

    if method_type == "password":
        cur.execute(
            "DELETE FROM user_auth_methods WHERE user_id = %s AND method_type = 'password';",
            (current_user.user_id,),
        )
        cur.execute(
            "UPDATE users SET password_hash = NULL WHERE user_id = %s;",
            (current_user.user_id,),
        )
    else:
        cur.execute(
            "DELETE FROM user_auth_methods WHERE user_id = %s AND method_type = %s;",
            (current_user.user_id, method_type),
        )

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "unlinked", "method_type": method_type}

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
def register_gateway(data: GatewayRegistration, current_user: User = Depends(get_current_user)):
    require_role(current_user, ["owner", "admin"])
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gateways (gateway_id, user_id, org_id, name, firmware_version, crypto_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (gateway_id) DO UPDATE
        SET user_id = EXCLUDED.user_id,
            org_id = EXCLUDED.org_id,
            name = EXCLUDED.name,
            firmware_version = EXCLUDED.firmware_version,
            crypto_id = EXCLUDED.crypto_id;
        """,
        (data.gateway_id, current_user.user_id, current_user.org_id,
         data.name, data.firmware_version, data.crypto_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "gateway_registered", "gateway_id": data.gateway_id}

@app.post("/sensors/register")
def register_sensor(data: SensorRegistration, current_user: User = Depends(get_current_user)):
    require_role(current_user, ["owner", "admin"])

    conn = get_db()
    cur = conn.cursor()

    # Ensure gateway exists and belongs to the same organisation
    cur.execute(
        "SELECT org_id FROM gateways WHERE gateway_id = %s;",
        (data.gateway_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Gateway not found")

    gateway_org_id = row[0]
    if gateway_org_id != current_user.org_id:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Gateway belongs to another organisation")

    # Insert/update sensor
    cur.execute(
        """
        INSERT INTO sensors (sensor_id, gateway_id, org_id, name, location, firmware_version)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (sensor_id) DO UPDATE
        SET gateway_id = EXCLUDED.gateway_id,
            org_id = EXCLUDED.org_id,
            name = EXCLUDED.name,
            location = EXCLUDED.location,
            firmware_version = EXCLUDED.firmware_version;
        """,
        (
            data.sensor_id,
            data.gateway_id,
            current_user.org_id,
            data.name,
            data.location,
            data.firmware_version,
        ),
    )

    # Clear existing capabilities
    cur.execute(
        "DELETE FROM sensor_capabilities WHERE sensor_id = %s;",
        (data.sensor_id,),
    )

    # Insert new capabilities
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

@app.post("/ota/jobs/create")
def create_ota_job(data: OtaJobCreate, current_user: User = Depends(get_current_user)):
    require_role(current_user, ["owner", "admin"])

    conn = get_db()
    cur = conn.cursor()

    # Validate target belongs to user's organisation
    if data.target_type == "gateway":
        cur.execute(
            "SELECT org_id FROM gateways WHERE gateway_id = %s;",
            (data.target_id,),
        )
    elif data.target_type == "sensor":
        cur.execute(
            "SELECT org_id FROM sensors WHERE sensor_id = %s;",
            (data.target_id,),
        )
    else:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid target_type")

    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Target not found")

    target_org_id = row[0]
    if target_org_id != current_user.org_id:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Target belongs to another organisation")

    # Create OTA job
    cur.execute(
        """
        INSERT INTO ota_jobs (target_type, target_id, firmware_version)
        VALUES (%s, %s, %s)
        RETURNING ota_id;
        """,
        (data.target_type, data.target_id, data.firmware_version),
    )
    ota_id = cur.fetchone()[0]

    # Update target desired firmware + status
    if data.target_type == "gateway":
        cur.execute(
            """
            UPDATE gateways
            SET desired_firmware_version = %s,
                ota_status = 'pending'
            WHERE gateway_id = %s;
            """,
            (data.firmware_version, data.target_id),
        )
    else:
        cur.execute(
            """
            UPDATE sensors
            SET desired_firmware_version = %s,
                ota_status = 'pending'
            WHERE sensor_id = %s;
            """,
            (data.firmware_version, data.target_id),
        )

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ota_job_created", "ota_id": ota_id}

@app.get("/ota/jobs/pending")
def get_pending_ota_jobs(gateway_id: str):
    conn = get_db()
    cur = conn.cursor()

    # Find gateway org
    cur.execute(
        "SELECT org_id FROM gateways WHERE gateway_id = %s;",
        (gateway_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Gateway not found")

    gw_org_id = row[0]

    # Pending jobs for this gateway and its sensors
    cur.execute(
        """
        SELECT j.ota_id, j.target_type, j.target_id, j.firmware_version
        FROM ota_jobs j
        LEFT JOIN gateways g
          ON j.target_type = 'gateway' AND j.target_id = g.gateway_id
        LEFT JOIN sensors s
          ON j.target_type = 'sensor' AND j.target_id = s.sensor_id
        WHERE j.status = 'pending'
          AND (
                (j.target_type = 'gateway' AND g.gateway_id = %s AND g.org_id = %s)
             OR (j.target_type = 'sensor' AND s.gateway_id = %s AND s.org_id = %s)
          );
        """,
        (gateway_id, gw_org_id, gateway_id, gw_org_id),
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    jobs = [
        {
            "ota_id": ota_id,
            "target_type": target_type,
            "target_id": target_id,
            "firmware_version": fw,
        }
        for ota_id, target_type, target_id, fw in rows
    ]

    return {"jobs": jobs}

@app.post("/ota/jobs/update")
def update_ota_job(data: OtaJobUpdate):
    conn = get_db()
    cur = conn.cursor()

    # Update job status + timestamps
    cur.execute(
        """
        UPDATE ota_jobs
        SET status = %s,
            error_message = %s,
            started_at = CASE WHEN %s = 'in_progress' THEN NOW() ELSE started_at END,
            completed_at = CASE WHEN %s IN ('success','failed') THEN NOW() ELSE completed_at END
        WHERE ota_id = %s;
        """,
        (data.status, data.error_message, data.status, data.status, data.ota_id),
    )

    # Fetch target info
    cur.execute(
        "SELECT target_type, target_id, firmware_version FROM ota_jobs WHERE ota_id = %s;",
        (data.ota_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.commit()
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="OTA job not found")

    target_type, target_id, firmware_version = row

    # Update target firmware + ota_status
    if data.status == "success":
        if target_type == "gateway":
            cur.execute(
                """
                UPDATE gateways
                SET firmware_version = %s,
                    desired_firmware_version = %s,
                    ota_status = 'success'
                WHERE gateway_id = %s;
                """,
                (firmware_version, firmware_version, target_id),
            )
        else:
            cur.execute(
                """
                UPDATE sensors
                SET firmware_version = %s,
                    desired_firmware_version = %s,
                    ota_status = 'success'
                WHERE sensor_id = %s;
                """,
                (firmware_version, firmware_version, target_id),
            )
    elif data.status == "failed":
        if target_type == "gateway":
            cur.execute(
                "UPDATE gateways SET ota_status = 'failed' WHERE gateway_id = %s;",
                (target_id,),
            )
        else:
            cur.execute(
                "UPDATE sensors SET ota_status = 'failed' WHERE sensor_id = %s;",
                (target_id,),
            )
    elif data.status == "in_progress":
        if target_type == "gateway":
            cur.execute(
                "UPDATE gateways SET ota_status = 'in_progress' WHERE gateway_id = %s;",
                (target_id,),
            )
        else:
            cur.execute(
                "UPDATE sensors SET ota_status = 'in_progress' WHERE sensor_id = %s;",
                (target_id,),
            )

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ota_job_updated", "ota_id": data.ota_id}
