from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import Json
from datetime import datetime, timedelta
import uuid
import os
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
import requests
import json
from db_helpers import get_sensors_and_capabilities_for_gateway
from email_backend import send_templated_email

app = FastAPI()

## note, full database scheme is located in repo /db/schema.sql 
## Public GitHub raw link for /db/schema.sql: https://raw.githubusercontent.com/chriskaye/WatchDogWeb/refs/heads/main/db/schema.sql
## Public Github raw link for /api/db_helpers: https://raw.githubusercontent.com/chriskaye/WatchDogWeb/refs/heads/main/api/db_helpers.py

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
    site_id: int
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
    default_site_id: int | None = None
    is_verified: bool
    is_watchdog_admin: bool = False
    # Support Access impersonation context — default False/None for every normal login.
    # Only set when get_current_user() resolves a support-view token (see Support Access
    # section below). is_support_session gates the mutation-blocking middleware;
    # support_admin_id is who to actually attribute actions/logs to during the session.
    is_support_session: bool = False
    support_admin_id: int | None = None

class UserCreate(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class InviteUser(BaseModel):
    email: str
    role: str  # site_role enum: 'global_admin' | 'site_admin' | 'global_viewer' | 'site_viewer'
    site_id: int | None = None  # required for 'site_admin'/'site_viewer'; must be None for global roles
    initial_password: str | None = None  # if set, admin assigns this password now (communicate
                                          # it via a different channel than the invite email —
                                          # that's the point: mitigates a mistyped-but-valid
                                          # invite email address getting account access via the
                                          # same channel the invite itself was sent through).
                                          # If omitted, the invited user sets their own password
                                          # after verifying their email.
    grant_watchdog_admin: bool = False   # sets users.is_watchdog_admin on the new account.
                                          # Only usable by an existing watchdog_admin — checked
                                          # in invite_user() below, in addition to the normal
                                          # site_id-based check for `role`. This is how a
                                          # platform admin actually provisions a colleague as
                                          # one, per your question — nothing else could do it.

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
    issued_at = datetime.utcnow()
    expire = issued_at + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    # "iat" lets get_current_user() reject tokens issued before a Suspend/Lock event
    # (sessions_invalidated_at), even though JWTs are otherwise stateless.
    to_encode.update({"exp": expire, "iat": issued_at})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- User lookup and current user dependency

def get_user_by_email(email: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, email, org_id, is_verified, password_hash, is_locked, is_suspended, suspend_reason, is_watchdog_admin FROM users WHERE email = %s;",
        (email,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    user_id, email, org_id, is_verified, password_hash, is_locked, is_suspended, suspend_reason, is_watchdog_admin = row
    user = User(user_id=user_id, email=email, org_id=org_id, is_verified=is_verified, is_watchdog_admin=is_watchdog_admin)
    return user, password_hash, is_locked, is_suspended, suspend_reason

def get_user_by_id(user_id: int):
    """Returns (User, sessions_invalidated_at) or None. sessions_invalidated_at is kept out
    of the public User model since it's an internal session-management detail, not something
    that should be returned from /users/me."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, email, org_id, is_verified, sessions_invalidated_at, is_watchdog_admin, default_site_id FROM users WHERE user_id = %s;",
        (user_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    uid, email, org_id, is_verified, sessions_invalidated_at, is_watchdog_admin, default_site_id = row
    user = User(user_id=uid, email=email, org_id=org_id, is_verified=is_verified, is_watchdog_admin=is_watchdog_admin, default_site_id=default_site_id)
    return user, sessions_invalidated_at

def _resolve_support_view_user(payload: dict) -> User:
    """Resolves a support-view token into a User representing the TARGET user (so every
    existing endpoint scopes data correctly with zero call-site changes), but stamps on
    is_support_session/support_admin_id so logging/middleware can tell the difference.
    Deliberately does NOT apply the target's own lock/suspend/sessions_invalidated_at
    checks — support access is admin-initiated and independent of the target's own
    session state (a support session should still work even if the target user is, say,
    mid-password-reset with their own sessions invalidated)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    admin_id = payload.get("admin_id")
    target_user_id = payload.get("target_user_id")
    grant_id = payload.get("grant_id")
    session_id = payload.get("session_id")
    if not all([admin_id, target_user_id, grant_id, session_id]):
        raise credentials_exception

    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM support_access_grants WHERE grant_id = %s AND user_id = %s AND expires_at > NOW() AND revoked_at IS NULL;",
        (grant_id, target_user_id),
    )
    grant_ok = cur.fetchone() is not None
    cur.execute("SELECT ended_at FROM support_access_sessions WHERE session_id = %s;", (session_id,))
    srow = cur.fetchone()
    cur.close(); conn.close()
    session_ok = srow is not None and srow[0] is None

    if not (grant_ok and session_ok):
        raise HTTPException(status_code=401, detail="Support Access session has ended or expired")

    result = get_user_by_id(int(target_user_id))
    if result is None:
        raise credentials_exception
    target_user, _sessions_invalidated_at = result
    target_user.is_support_session = True
    target_user.support_admin_id = int(admin_id)
    return target_user

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise credentials_exception

    if payload.get("typ") == "support_view":
        return _resolve_support_view_user(payload)

    try:
        user_id = payload.get("sub")
        issued_at = payload.get("iat")
        if user_id is None or issued_at is None:
            raise credentials_exception
        user_id = int(user_id)  # sub is always a string in the token; cast back for the DB lookup
        issued_at = datetime.utcfromtimestamp(issued_at)
    except ValueError:
        raise credentials_exception

    result = get_user_by_id(user_id)
    if result is None:
        raise credentials_exception
    user, sessions_invalidated_at = result

    if sessions_invalidated_at is not None and issued_at < sessions_invalidated_at:
        # Token predates a Suspend/Lock/forced-signout event — reject even though it hasn't expired.
        raise HTTPException(
            status_code=401,
            detail="Session has been invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return user

# --- Support Access: block any mutation made under a support-view token, at the
# transport layer, so it's a structural guarantee rather than something every route
# handler has to remember to check. Normal tokens are completely unaffected — this only
# ever fires for requests bearing a token whose payload decodes with typ=="support_view".
@app.middleware("http")
async def block_support_session_mutations(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                payload = jwt.decode(auth[7:], SECRET_KEY, algorithms=[ALGORITHM])
                if payload.get("typ") == "support_view":
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Support Access sessions are read-only"},
                    )
            except JWTError:
                pass  # not a valid token at all — let the route's own auth dependency reject it as usual
    return await call_next(request)

# --- Access control (user_site_roles / role_hierarchy) ---
#
# Rank values confirmed: global_admin=4, site_admin=3, global_viewer=2, site_viewer=1,
# no_access=0 (higher = more privileged). Read from role_hierarchy at query time below
# rather than hardcoded, so this doesn't drift if the ranks are ever re-tuned.

SITE_ROLE_ADMIN_LEVEL = {"global_admin", "site_admin"}
SITE_ROLE_ANY_ACCESS = {"global_admin", "site_admin", "global_viewer", "site_viewer"}

def get_global_role(cur, user_id: int) -> str | None:
    """A user has at most one global (site_id IS NULL) grant — enforced by a unique index."""
    cur.execute(
        "SELECT role FROM user_site_roles WHERE user_id = %s AND site_id IS NULL;",
        (user_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None

def get_site_role(cur, user_id: int, site_id: int) -> str | None:
    """A user has at most one grant per site — enforced by a unique index."""
    cur.execute(
        "SELECT role FROM user_site_roles WHERE user_id = %s AND site_id = %s;",
        (user_id, site_id),
    )
    row = cur.fetchone()
    return row[0] if row else None

def get_role_rank(cur, role: str | None) -> int:
    if role is None:
        return 0  # equivalent to no_access
    cur.execute("SELECT rank FROM role_hierarchy WHERE role = %s;", (role,))
    row = cur.fetchone()
    return row[0] if row else 0

def get_user_best_rank(cur, user_id: int) -> int:
    """The user's highest-ranked grant across their global role and every site role they hold."""
    global_role = get_global_role(cur, user_id)
    if global_role:
        return get_role_rank(cur, global_role)
    cur.execute("SELECT role FROM user_site_roles WHERE user_id = %s;", (user_id,))
    return max((get_role_rank(cur, role) for (role,) in cur.fetchall()), default=0)

def get_admin_site_ids(cur, user_id: int) -> list[int]:
    """Sites where this user holds site_admin specifically (not site_viewer)."""
    cur.execute("SELECT site_id FROM user_site_roles WHERE user_id = %s AND role = 'site_admin';", (user_id,))
    return [r[0] for r in cur.fetchall()]

def get_user_site_ids(cur, user_id: int) -> list[int]:
    """Every site this user holds ANY site-scoped role on (site_admin or site_viewer)."""
    cur.execute("SELECT site_id FROM user_site_roles WHERE user_id = %s AND site_id IS NOT NULL;", (user_id,))
    return [r[0] for r in cur.fetchall()]

def authorize_admin_action_on_user(cur, actor: User, target_user_id: int, target_org_id: int, rank_relation: str):
    """
    Shared authorization for admin_delete_user / lock_user / suspend_user's non-self path.
    rank_relation: 'strict' (actor must strictly outrank target — Lock, Delete) or
                   'gte' (same-or-lower rank allowed — Suspend).

    - Viewers (global_viewer, site_viewer) can NEVER act here, full stop, regardless of rank —
      only global_admin or site_admin qualify as "admin" at all.
    - global_admin acts on anyone in the org.
    - site_admin may only act on a target who shares at least one site with them (i.e. the
      target holds some role — global or site-scoped — on a site the actor administers),
      and only subject to the rank relation above.
    """
    if target_org_id != actor.org_id:
        raise HTTPException(status_code=403, detail="User belongs to another organisation")

    if get_global_role(cur, actor.user_id) == "global_admin":
        return

    actor_site_ids = set(get_admin_site_ids(cur, actor.user_id))
    if not actor_site_ids:
        raise HTTPException(status_code=403, detail="Admin permission required")

    target_site_ids = set(get_user_site_ids(cur, target_user_id))
    if not (actor_site_ids & target_site_ids):
        raise HTTPException(status_code=403, detail="You do not share a site with this user")

    actor_rank = get_user_best_rank(cur, actor.user_id)
    target_rank = get_user_best_rank(cur, target_user_id)
    ok = actor_rank > target_rank if rank_relation == "strict" else actor_rank >= target_rank
    if not ok:
        raise HTTPException(status_code=403, detail="Insufficient rank for this action")

def log_event(cur, org_id: int, event_type: str, actor_user_id: int | None,
               target_type: str, target_id: str | None, details: dict | None):
    """Writes to the per-org event log table. Table name is built from an int org_id we
    already trust (never from request input), so this isn't a SQL-injection vector."""
    tbl = f"org_event_log_org_{int(org_id)}"
    cur.execute(
        f"INSERT INTO {tbl} (event_type, actor_user_id, target_type, target_id, details) "
        f"VALUES (%s, %s, %s, %s, %s::jsonb);",
        (event_type, actor_user_id, target_type, target_id,
         json.dumps(details) if details is not None else None),
    )

def log_platform_event(cur, event_type: str, actor_user_id: int | None,
                        target_type: str, target_id: str | None, details: dict | None):
    """Writes to platform_event_log — for is_watchdog_admin catalog actions that have no
    org_id (mcu_variants, battery_profiles, device_registry, sensor_module_types,
    module_mcu_compatibility). Separate from log_event()'s per-org tables."""
    cur.execute(
        "INSERT INTO platform_event_log (event_type, actor_user_id, target_type, target_id, details) "
        "VALUES (%s, %s, %s, %s, %s::jsonb);",
        (event_type, actor_user_id, target_type, target_id,
         json.dumps(details) if details is not None else None),
    )

def require_org_admin(cur, user: User):
    """Global-Admin-or-higher only (org-wide actions: backups settings, org GDPR deletion,
    etc). Rank-based rather than a literal 'global_admin' string match — was originally
    written this way so watchdog_admin (formerly a rank-5 site_role value) would inherit
    global_admin's powers automatically. That role no longer exists (replaced by the
    users.is_watchdog_admin flag, see require_platform_admin), so this is now equivalent to
    a plain global_admin check, but left rank-based since it's still correct and costs
    nothing extra."""
    if get_user_best_rank(cur, user.user_id) < get_role_rank(cur, "global_admin"):
        raise HTTPException(status_code=403, detail="Global Admin permission required")

def require_org_access(cur, user: User, admin: bool = False):
    """
    Org-wide check for resources not yet wired up to a specific site_id
    (gateways/sensors/OTA jobs currently register without a site_id — see Phase B).
    admin=True  -> must be global_admin-or-higher
    admin=False -> must be global_admin-or-higher, or global_viewer
    """
    role = get_global_role(cur, user.user_id)
    if get_role_rank(cur, role) >= get_role_rank(cur, "global_admin"):
        return
    if not admin and role == "global_viewer":
        return
    raise HTTPException(status_code=403, detail="Insufficient permissions")

def require_site_access(cur, user: User, org_id: int, site_id: int, admin: bool = False):
    """
    Full site-scoped check, for use once endpoints carry a site_id (Phase B onward).
    Confirms the site belongs to the user's org, then checks global or site-level role.
    """
    cur.execute("SELECT org_id FROM sites WHERE site_id = %s;", (site_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Site not found")
    if row[0] != org_id:
        raise HTTPException(status_code=403, detail="Site belongs to another organisation")

    global_role = get_global_role(cur, user.user_id)
    if get_role_rank(cur, global_role) >= get_role_rank(cur, "global_admin"):
        return
    if not admin and global_role == "global_viewer":
        return

    site_role = get_site_role(cur, user.user_id, site_id)
    if admin and site_role == "site_admin":
        return
    if not admin and site_role in ("site_admin", "site_viewer"):
        return

    raise HTTPException(status_code=403, detail="Insufficient permissions for this site")

def require_platform_admin(cur, user: User):
    """Gate for the shared/global hardware catalog (mcu_variants, mcu_variant_gpio_pins,
    module_mcu_compatibility, device_registry, sensor_module_types, and Support Access
    admin actions). Checks the flat users.is_watchdog_admin flag directly — deliberately
    NOT rank-based like require_org_admin, and no longer tied to user_site_roles/
    role_hierarchy at all (the old 'watchdog_admin' site_role + rank-5 role_hierarchy row
    have been removed from the schema). This is intentional: platform-staff status and
    org-level rank are different axes entirely, and a flat flag makes it structurally
    impossible for platform access to leak into org-scoped authorization by accident —
    unlike the old rank-based version, which was only safe because every org-scoped check
    happened to also verify target_org_id == actor.org_id independently."""
    if not user.is_watchdog_admin:
        raise HTTPException(status_code=403, detail="WatchDog platform admin permission required")

# --- Sending Email stub

def send_verification_email(email: str, token: str):
    verify_url = FRONTEND_BASE_URL + f"/verify?token={token}"
    send_templated_email(
        email, "Verify your WatchDog account",
        f"Welcome to WatchDog. Verify your account by visiting:\n{verify_url}\n\nThis link expires in 24 hours.",
    )
    print(f"[DEBUG] Send verification email to {email}: {verify_url}")

# --- verification tokens (user_verification_tokens table) ---

def create_verification_token(cur, user_id: int, reason: str, expires_hours: int = 24) -> str:
    """Issue a verification token row for a user within an existing cursor/transaction.

    reason must be one of the verification_reason enum values:
    'signup', 'account_deletion', 'password_reset', 'sso_removal', 'account_unlock'.
    """
    token = str(uuid.uuid4())
    expires = datetime.utcnow() + timedelta(hours=expires_hours)
    cur.execute(
        """
        INSERT INTO user_verification_tokens (user_id, token, reason, expires_at)
        VALUES (%s, %s, %s, %s);
        """,
        (user_id, token, reason, expires),
    )
    return token

# --- create organisations and unverified users

def create_org_and_owner(email: str, password_hash: str | None, provider: str | None, sub: str | None):
    conn = get_db()
    cur = conn.cursor()

    # create organisation
    cur.execute(
        "INSERT INTO organisations (name) VALUES (%s) RETURNING org_id;",
        (f"{email}'s Organisation",)
    )
    org_id = cur.fetchone()[0]

    # create user as owner (unverified)
    cur.execute(
        """
        INSERT INTO users (email, password_hash, is_verified, org_id)
        VALUES (%s, %s, FALSE, %s)
        RETURNING user_id;
        """,
        (email, password_hash, org_id),
    )
    user_id = cur.fetchone()[0]

    # the first user of an org is granted org-wide Global Admin (site_id = NULL)
    cur.execute(
        """
        INSERT INTO user_site_roles (user_id, site_id, role, granted_by)
        VALUES (%s, NULL, 'global_admin', %s);
        """,
        (user_id, user_id),
    )

    # record auth method(s)
    if password_hash:
        cur.execute(
            "INSERT INTO user_auth_methods (user_id, method_type) VALUES (%s, %s);",
            (user_id, "password"),
        )
    if provider and sub:
        cur.execute(
            "INSERT INTO user_auth_methods (user_id, method_type, provider_sub) VALUES (%s, %s, %s);",
            (user_id, provider, sub),
        )

    token = create_verification_token(cur, user_id, "signup")

    log_event(cur, org_id, "org_registered", user_id, "organisation", str(org_id), {"email": email})
    conn.commit()
    cur.close()
    conn.close()

    send_verification_email(email, token)
    return user_id

def create_unverified_user_in_org(email: str, org_id: int, role: str, site_id: int | None,
                                   granted_by: int, password_hash: str | None = None,
                                   is_watchdog_admin: bool = False):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (email, is_verified, org_id, password_hash, is_watchdog_admin)
        VALUES (%s, FALSE, %s, %s, %s)
        RETURNING user_id;
        """,
        (email, org_id, password_hash, is_watchdog_admin),
    )
    user_id = cur.fetchone()[0]

    if password_hash:
        cur.execute(
            "INSERT INTO user_auth_methods (user_id, method_type) VALUES (%s, 'password');",
            (user_id,),
        )

    cur.execute(
        """
        INSERT INTO user_site_roles (user_id, site_id, role, granted_by)
        VALUES (%s, %s, %s, %s);
        """,
        (user_id, site_id, role, granted_by),
    )

    token = create_verification_token(cur, user_id, "signup")

    log_event(cur, org_id, "user_invited", granted_by, "user", str(user_id),
              {"email": email, "role": role, "site_id": site_id})
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

def _log_login_attempt(org_id: int, user_id: int, event_type: str, ip: str | None, reason: str | None = None):
    """Best-effort login event logging on its own short-lived connection — /token doesn't
    otherwise touch the DB directly (get_user_by_email opens/closes its own connection)."""
    details = {"ip": ip}
    if reason:
        details["reason"] = reason
    conn = get_db()
    cur = conn.cursor()
    log_event(cur, org_id, event_type, user_id, "user", str(user_id), details)
    conn.commit()
    cur.close()
    conn.close()

@app.post("/token", response_model=Token) # JWT login
async def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    client_ip = request.client.host if request.client else None
    result = get_user_by_email(form_data.username)
    if not result:
        # No resolvable user -> no org to log the attempt against.
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    user, password_hash, is_locked, is_suspended, suspend_reason = result

    if not password_hash or not verify_password(form_data.password, password_hash):
        _log_login_attempt(user.org_id, user.user_id, "login_failed", client_ip, "invalid_credentials")
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not user.is_verified:
        _log_login_attempt(user.org_id, user.user_id, "login_failed", client_ip, "not_verified")
        raise HTTPException(status_code=403, detail="Email not verified")

    if is_locked:
        _log_login_attempt(user.org_id, user.user_id, "login_failed", client_ip, "locked")
        raise HTTPException(status_code=403, detail="Account is locked. Use the account recovery flow to regain access.")

    if is_suspended:
        _log_login_attempt(user.org_id, user.user_id, "login_failed", client_ip, "suspended")
        detail = "Account is suspended."
        if suspend_reason:
            detail += f" Reason: {suspend_reason}"
        raise HTTPException(status_code=403, detail=detail)

    _log_login_attempt(user.org_id, user.user_id, "login_success", client_ip)
    access_token = create_access_token(data={"sub": str(user.user_id)})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/verify") # process email verification links
def verify_email(token: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT token_id, user_id, expires_at, used_at
        FROM user_verification_tokens
        WHERE token = %s AND reason = 'signup';
        """,
        (token,),
    )
    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid verification token")

    token_id, user_id, expires_at, used_at = row

    if used_at is not None:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Token already used")

    if datetime.utcnow() > expires_at:
        # signup token expired -> the account was never verified, so drop it;
        # ON DELETE CASCADE on user_verification_tokens.user_id cleans up the token row too
        cur.execute("DELETE FROM users WHERE user_id = %s AND is_verified = FALSE;", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Verification expired. Please register again.")

    cur.execute("UPDATE users SET is_verified = TRUE WHERE user_id = %s;", (user_id,))
    cur.execute("UPDATE user_verification_tokens SET used_at = NOW() WHERE token_id = %s;", (token_id,))

    # If the inviting admin didn't set a default password, this user has none yet —
    # kick off the "set your own password" flow now that their email is confirmed.
    cur.execute("SELECT password_hash, email FROM users WHERE user_id = %s;", (user_id,))
    password_hash, email = cur.fetchone()
    password_setup_required = password_hash is None
    if password_setup_required:
        setup_token = create_verification_token(cur, user_id, "password_reset")
        setup_url = FRONTEND_BASE_URL + f"/set-password?token={setup_token}"
        send_templated_email(
            email, "Set your WatchDog password",
            f"Set your WatchDog password by visiting:\n{setup_url}\n\nThis link expires in 24 hours.",
        )
        print(f"[DEBUG] Send password setup link to {email}: {setup_url}")

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "verified", "password_setup_required": password_setup_required}

@app.post("/users/password/request_set")
def request_initial_password_setup(email: str):
    """For a verified user who still has no password (admin didn't preset one, and they
    missed/lost the link from /verify). Always returns success regardless of eligibility,
    to avoid leaking account existence/state via response differences."""
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT user_id, org_id FROM users WHERE email = %s AND is_verified = TRUE AND password_hash IS NULL;",
        (email,),
    )
    row = cur.fetchone()
    if row:
        token = create_verification_token(cur, row[0], "password_reset")
        log_event(cur, row[1], "password_reset_requested", None, "user", str(row[0]), None)
        conn.commit()
        setup_url = FRONTEND_BASE_URL + f"/set-password?token={token}"
        send_templated_email(
            email, "Set your WatchDog password",
            f"Set your WatchDog password by visiting:\n{setup_url}\n\nThis link expires in 24 hours.",
        )
        print(f"[DEBUG] Send password setup link to {email}: {setup_url}")
    cur.close(); conn.close()
    return {"status": "if_eligible_email_sent"}

class SetPasswordFromToken(BaseModel):
    token: str
    new_password: str

@app.post("/users/password/set")
def set_password_from_token(data: SetPasswordFromToken):
    """Confirms a password_reset token and sets the password. Used both for the
    invited-user first-password-setup flow and can double as a general forgot-password
    flow later (same token reason, same mechanics)."""
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT token_id, user_id, expires_at, used_at FROM user_verification_tokens WHERE token = %s AND reason = 'password_reset';",
        (data.token,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Invalid token")
    token_id, user_id, expires_at, used_at = row
    if used_at is not None or datetime.utcnow() > expires_at:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Token expired or already used")
    if len(data.new_password) < 8:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    new_hash = get_password_hash(data.new_password)
    cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s RETURNING org_id;", (new_hash, user_id))
    set_org_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO user_auth_methods (user_id, method_type) VALUES (%s, 'password') "
        "ON CONFLICT (user_id, method_type) DO NOTHING;",
        (user_id,),
    )
    cur.execute("UPDATE user_verification_tokens SET used_at = NOW() WHERE token_id = %s;", (token_id,))
    log_event(cur, set_org_id, "password_reset_completed", None, "user", str(user_id), None)
    conn.commit()
    cur.close(); conn.close()
    return {"status": "password_set"}

class ChangePassword(BaseModel):
    current_password: str
    new_password: str

@app.post("/users/me/password/change")
def change_own_password(data: ChangePassword, current_user: User = Depends(get_current_user)):
    """Self-service password rotation for a user who already has a working password —
    distinct from /users/password/request_set (only works when password_hash IS NULL) and
    /users/unlock/request (only works when locked). Bumps sessions_invalidated_at on
    success, same as lock/suspend — this deliberately also invalidates the token used to
    make THIS request, forcing a fresh login. FRONTEND NOTE for FE-5: treat a successful
    response as "log the user out and return to login", not as "still logged in"."""
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE user_id = %s;", (current_user.user_id,))
    row = cur.fetchone()
    if not row or not row[0] or not verify_password(data.current_password, row[0]):
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new_hash = get_password_hash(data.new_password)
    cur.execute(
        "UPDATE users SET password_hash = %s, sessions_invalidated_at = NOW() WHERE user_id = %s;",
        (new_hash, current_user.user_id),
    )
    log_event(cur, current_user.org_id, "password_changed", current_user.user_id, "user", str(current_user.user_id), None)
    conn.commit(); cur.close(); conn.close()
    return {"status": "password_changed"}

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

    # Phase C: evaluate alert_rules for this reading (see note above evaluate_alert_rules)
    serial_number = resolve_serial_number(cur, data.gateway_id, data.sensor_id)
    if serial_number:
        evaluate_alert_rules(cur, serial_number, {
            "temperature": data.temperature,
            "humidity": data.humidity,
            "battery": data.battery,
            "motion": data.motion,
        })

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ingested", "gateway_id": data.gateway_id, "sensor_id": data.sensor_id}

@app.get("/sensors/{serial_number}/readings")
def get_sensor_readings(
    serial_number: str,
    from_date: str | None = None,
    to_date: str | None = None,
    metric: str | None = None,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
):
    """RPT-1: time-series read endpoint backing dashboard trend charts and report
    templates. Despite the path (kept matching the roadmap's original naming), this works
    for gateways too — a gateway's own onboard sensing shares the same sensor_data table.

    from_date/to_date are ISO-8601 timestamps (defaults to the last 24h if from_date is
    omitted). metric filters to one of temperature/humidity/battery/motion; omitted
    returns all four per row. Read-only — any site viewer-or-above can call this, matching
    the read-level check other GET endpoints in this file use (require_site_access with
    admin=False), not the admin-only bar factory_reset/deprovision use.
    """
    conn = get_db(); cur = conn.cursor()
    device = get_device_org_and_site(cur, serial_number)
    if not device:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found")
    device_org_id, device_site_id = device
    require_site_access(cur, current_user, device_org_id, device_site_id, admin=False)

    cur.execute("SELECT device_type FROM device_registry WHERE serial_number = %s;", (serial_number,))
    reg_row = cur.fetchone()
    device_type = reg_row[0] if reg_row else None
    if device_type not in ("gateway", "sensor"):
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found in registry")

    if device_type == "sensor":
        cur.execute("SELECT sensor_id FROM sensors WHERE serial_number = %s;", (serial_number,))
        row = cur.fetchone()
        target_col, target_val = "sensor_id", (row[0] if row else None)
    else:
        cur.execute("SELECT gateway_id FROM gateways WHERE serial_number = %s;", (serial_number,))
        row = cur.fetchone()
        target_col, target_val = "gateway_id", (row[0] if row else None)

    if not target_val:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found")

    limit = max(1, min(limit, 5000))
    query = f"SELECT ts, temperature, humidity, motion, battery FROM sensor_data WHERE {target_col} = %s"
    params = [target_val]
    if device_type == "gateway":
        # Exclude readings relayed from child sensors — those belong under their own
        # serial_number and would otherwise be double-counted against the gateway's own.
        query += " AND (sensor_id IS NULL OR sensor_id = '')"
    if from_date:
        query += " AND ts >= %s"
        params.append(from_date)
    else:
        query += " AND ts >= NOW() - INTERVAL '24 hours'"
    if to_date:
        query += " AND ts <= %s"
        params.append(to_date)
    query += " ORDER BY ts DESC LIMIT %s;"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close(); conn.close()

    readings = []
    for ts, temperature, humidity, motion, battery in rows:
        point = {"ts": ts}
        if metric is None or metric == "temperature":
            point["temperature"] = temperature
        if metric is None or metric == "humidity":
            point["humidity"] = humidity
        if metric is None or metric == "motion":
            point["motion"] = motion
        if metric is None or metric == "battery":
            point["battery"] = battery
        readings.append(point)

    return {"serial_number": serial_number, "readings": readings}

@app.post("/users/invite") # users invited by org admins
def invite_user(data: InviteUser, current_user: User = Depends(get_current_user)):
    # 'watchdog_admin' is no longer a site_role at all (it's the flat users.is_watchdog_admin
    # flag now — see require_platform_admin), so it was never a candidate for this whitelist
    # in the first place. Kept the explicit rejection anyway since InviteUser.role is
    # arbitrary user input, not something we should trust to already exclude it.
    if data.role not in ("global_admin", "site_admin", "global_viewer", "site_viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")

    is_global = data.role in ("global_admin", "global_viewer")
    if is_global and data.site_id is not None:
        raise HTTPException(status_code=400, detail="site_id must be omitted for a global role")
    if not is_global and data.site_id is None:
        raise HTTPException(status_code=400, detail="site_id is required for a site-scoped role")

    if data.initial_password is not None and len(data.initial_password) < 8:
        raise HTTPException(status_code=400, detail="initial_password must be at least 8 characters")

    conn = get_db()
    cur = conn.cursor()

    if data.grant_watchdog_admin:
        # Only an existing platform admin can provision a colleague as one — this is the
        # entire answer to "how does a new WatchDog admin ever get made".
        require_platform_admin(cur, current_user)

    if is_global:
        require_org_admin(cur, current_user)
    else:
        require_site_access(cur, current_user, current_user.org_id, data.site_id, admin=True)

    cur.execute("SELECT user_id FROM users WHERE email = %s;", (data.email,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        raise HTTPException(status_code=400, detail="User already exists")

    initial_hash = get_password_hash(data.initial_password) if data.initial_password else None
    user_id = create_unverified_user_in_org(
        data.email, current_user.org_id, data.role, data.site_id, current_user.user_id,
        initial_hash, data.grant_watchdog_admin,
    )
    return {
        "status": "invited", "user_id": user_id,
        "password_preset": initial_hash is not None,
        "watchdog_admin_granted": data.grant_watchdog_admin,
    }

# add this endpoint, e.g. near list_auth_methods
@app.get("/users/me", response_model=User)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/users/me/roles")
def get_my_roles(current_user: User = Depends(get_current_user)):
    """Frontend needs this to decide what to render — there was no way to know the
    logged-in user's role(s) after User dropped its flat `role` field for the site-scoped
    model. Returns the global (org-wide) role if any, every site-scoped role held, and
    whether they're a WatchDog platform admin (separate axis — see require_platform_admin)."""
    conn = get_db(); cur = conn.cursor()
    global_role = get_global_role(cur, current_user.user_id)
    cur.execute("SELECT site_id, role FROM user_site_roles WHERE user_id = %s AND site_id IS NOT NULL;", (current_user.user_id,))
    site_roles = [{"site_id": r[0], "role": r[1]} for r in cur.fetchall()]
    cur.close(); conn.close()
    return {
        "global_role": global_role,
        "site_roles": site_roles,
        "is_watchdog_admin": current_user.is_watchdog_admin,
    }

class DefaultSiteUpdate(BaseModel):
    site_id: int | None = None

@app.post("/users/me/default_site")
def set_default_site(data: DefaultSiteUpdate, current_user: User = Depends(get_current_user)):
    """Sets/clears the calling user's default_site_id (DB-1). Agreed approach: link to an
    existing site rather than duplicate address data onto users. Pass site_id=null to clear."""
    conn = get_db(); cur = conn.cursor()
    if data.site_id is not None:
        cur.execute("SELECT org_id FROM sites WHERE site_id = %s;", (data.site_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            raise HTTPException(status_code=404, detail="Site not found")
        if row[0] != current_user.org_id:
            cur.close(); conn.close()
            raise HTTPException(status_code=403, detail="Site belongs to another organisation")
        _accessible_site_ids_or_none(cur, current_user, data.site_id)  # raises 403 if not accessible
    cur.execute("UPDATE users SET default_site_id = %s WHERE user_id = %s;", (data.site_id, current_user.user_id))
    conn.commit(); cur.close(); conn.close()
    return {"status": "default_site_updated", "default_site_id": data.site_id}

@app.get("/users")
def list_org_users(current_user: User = Depends(get_current_user)):
    """Org roster for the Users & Groups page. Global-role users (admin or viewer) see
    everyone in the org; site-scoped users only see people who share a site with them."""
    conn = get_db(); cur = conn.cursor()
    if get_global_role(cur, current_user.user_id):
        cur.execute(
            "SELECT user_id, email, is_verified, is_locked, is_suspended FROM users WHERE org_id = %s ORDER BY email;",
            (current_user.org_id,),
        )
        rows = cur.fetchall()
    else:
        my_sites = get_user_site_ids(cur, current_user.user_id)
        if not my_sites:
            cur.close(); conn.close()
            return {"users": []}
        cur.execute(
            """
            SELECT DISTINCT u.user_id, u.email, u.is_verified, u.is_locked, u.is_suspended
            FROM users u JOIN user_site_roles usr ON usr.user_id = u.user_id
            WHERE u.org_id = %s AND usr.site_id = ANY(%s) ORDER BY u.email;
            """,
            (current_user.org_id, my_sites),
        )
        rows = cur.fetchall()

    result = []
    for uid, email, is_verified, is_locked, is_suspended in rows:
        global_role = get_global_role(cur, uid)
        cur.execute("SELECT site_id, role FROM user_site_roles WHERE user_id = %s AND site_id IS NOT NULL;", (uid,))
        site_roles = [{"site_id": r[0], "role": r[1]} for r in cur.fetchall()]
        result.append({
            "user_id": uid, "email": email, "is_verified": is_verified,
            "is_locked": is_locked, "is_suspended": is_suspended,
            "global_role": global_role, "site_roles": site_roles,
        })
    cur.close(); conn.close()
    return {"users": result}

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
    # PARKED: real OAuth code exchange needs a registered domain + email service, which
    # don't exist yet. Previously this silently "succeeded" using a fake stub provider_sub
    # (f"stub-{provider}-sub"), which would have written misleading rows into
    # user_auth_methods and made it look like SSO worked in a demo when it didn't actually
    # authenticate anyone. Failing loudly is safer than a convincing fake.
    raise HTTPException(status_code=501, detail=f"SSO login via {data.provider} is not available yet")

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

    log_event(cur, current_user.org_id, "sso_unlinked", current_user.user_id, "user", str(current_user.user_id),
              {"method_type": method_type})
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
    cur.execute("SELECT org_id FROM users WHERE user_id = %s;", (data.user_id,))
    owner_row = cur.fetchone()
    if owner_row:
        log_event(cur, owner_row[0], "crypto_profile_created", None, "crypto_profile", str(crypto_id),
                  {"name": data.name, "mode": data.mode})
    conn.commit()
    cur.close()
    conn.close()
    return {"crypto_id": crypto_id}


@app.post("/gateways/register")
def register_gateway(data: GatewayRegistration, current_user: User = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    require_site_access(cur, current_user, current_user.org_id, data.site_id, admin=True)
    cur.execute(
        """
        INSERT INTO gateways (gateway_id, user_id, org_id, site_id, name, firmware_version, crypto_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (gateway_id) DO UPDATE
        SET user_id = EXCLUDED.user_id,
            org_id = EXCLUDED.org_id,
            site_id = EXCLUDED.site_id,
            name = EXCLUDED.name,
            firmware_version = EXCLUDED.firmware_version,
            crypto_id = EXCLUDED.crypto_id;
        """,
        (data.gateway_id, current_user.user_id, current_user.org_id, data.site_id,
         data.name, data.firmware_version, data.crypto_id),
    )
    log_event(cur, current_user.org_id, "gateway_registered", current_user.user_id, "gateway", data.gateway_id,
              {"name": data.name, "site_id": data.site_id})
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "gateway_registered", "gateway_id": data.gateway_id}

@app.post("/sensors/register")
def register_sensor(data: SensorRegistration, current_user: User = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()

    # Ensure gateway exists and belongs to the same organisation
    cur.execute(
        "SELECT org_id, site_id FROM gateways WHERE gateway_id = %s;",
        (data.gateway_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Gateway not found")

    gateway_org_id, gateway_site_id = row
    if gateway_org_id != current_user.org_id:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Gateway belongs to another organisation")

    # A sensor inherits its site from its gateway rather than taking one directly —
    # a sensor can't be on a different site than the gateway it reports through.
    if gateway_site_id is None:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Gateway has no site assigned yet; assign one before adding sensors")
    require_site_access(cur, current_user, current_user.org_id, gateway_site_id, admin=True)

    # Insert/update sensor
    cur.execute(
        """
        INSERT INTO sensors (sensor_id, gateway_id, org_id, site_id, name, location, firmware_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (sensor_id) DO UPDATE
        SET gateway_id = EXCLUDED.gateway_id,
            org_id = EXCLUDED.org_id,
            site_id = EXCLUDED.site_id,
            name = EXCLUDED.name,
            location = EXCLUDED.location,
            firmware_version = EXCLUDED.firmware_version;
        """,
        (
            data.sensor_id,
            data.gateway_id,
            current_user.org_id,
            gateway_site_id,
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

    log_event(cur, current_user.org_id, "sensor_registered", current_user.user_id, "sensor", data.sensor_id,
              {"name": data.name, "gateway_id": data.gateway_id})
    conn.commit()
    cur.close()
    conn.close()

    return {"status": "sensor_registered", "sensor_id": data.sensor_id}

def _accessible_site_ids_or_none(cur, current_user: User, site_id_filter: int | None):
    """Returns None if the user has a global role (see everything), otherwise the list of
    site_ids they may see (intersected with an explicit ?site_id= filter if given)."""
    if get_global_role(cur, current_user.user_id):
        return None if site_id_filter is None else [site_id_filter]
    accessible = get_user_site_ids(cur, current_user.user_id)
    if site_id_filter is not None:
        if site_id_filter not in accessible:
            raise HTTPException(status_code=403, detail="No access to this site")
        return [site_id_filter]
    return accessible

@app.get("/gateways")
def list_gateways(site_id: int | None = None, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    site_ids = _accessible_site_ids_or_none(cur, current_user, site_id)
    if site_ids is None:
        cur.execute(
            "SELECT gateway_id, name, site_id, firmware_version, serial_number, is_active, battery_profile_id FROM gateways WHERE org_id = %s ORDER BY name;",
            (current_user.org_id,),
        )
    elif not site_ids:
        cur.close(); conn.close()
        return {"gateways": []}
    else:
        cur.execute(
            "SELECT gateway_id, name, site_id, firmware_version, serial_number, is_active, battery_profile_id FROM gateways WHERE org_id = %s AND site_id = ANY(%s) ORDER BY name;",
            (current_user.org_id, site_ids),
        )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"gateways": [
        {"gateway_id": r[0], "name": r[1], "site_id": r[2], "firmware_version": r[3], "serial_number": r[4],
         "is_active": r[5], "battery_profile_id": r[6]}
        for r in rows
    ]}

@app.get("/sensors")
def list_sensors(site_id: int | None = None, gateway_id: str | None = None, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    site_ids = _accessible_site_ids_or_none(cur, current_user, site_id)
    base_query = "SELECT sensor_id, name, gateway_id, site_id, location, firmware_version, serial_number, is_active, battery_profile_id FROM sensors WHERE org_id = %s"
    params = [current_user.org_id]
    if site_ids is not None:
        if not site_ids:
            cur.close(); conn.close()
            return {"sensors": []}
        base_query += " AND site_id = ANY(%s)"
        params.append(site_ids)
    if gateway_id is not None:
        base_query += " AND gateway_id = %s"
        params.append(gateway_id)
    base_query += " ORDER BY name;"
    cur.execute(base_query, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"sensors": [
        {"sensor_id": r[0], "name": r[1], "gateway_id": r[2], "site_id": r[3], "location": r[4],
         "firmware_version": r[5], "serial_number": r[6], "is_active": r[7], "battery_profile_id": r[8]}
        for r in rows
    ]}

@app.post("/gateways/soft_delete")
def soft_delete_gateway(data: SoftDeleteGateway):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE gateways SET is_active = FALSE WHERE gateway_id = %s RETURNING org_id;",
        (data.gateway_id,),
    )
    row = cur.fetchone()
    if row and row[0] is not None:
        log_event(cur, row[0], "gateway_soft_deleted", None, "gateway", data.gateway_id, None)
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "gateway_soft_deleted", "gateway_id": data.gateway_id}


@app.post("/sensors/soft_delete")
def soft_delete_sensor(data: SoftDeleteSensor):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE sensors SET is_active = FALSE WHERE sensor_id = %s RETURNING org_id;",
        (data.sensor_id,),
    )
    row = cur.fetchone()
    if row and row[0] is not None:
        log_event(cur, row[0], "sensor_soft_deleted", None, "sensor", data.sensor_id, None)
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "sensor_soft_deleted", "sensor_id": data.sensor_id}


@app.post("/gateways/hard_delete")
def hard_delete_gateway_endpoint(data: HardDeleteGateway):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT org_id FROM gateways WHERE gateway_id = %s;", (data.gateway_id,))
    org_row = cur.fetchone()
    cur.execute("SELECT hard_delete_gateway(%s);", (data.gateway_id,))
    if org_row and org_row[0] is not None:
        log_event(cur, org_row[0], "gateway_hard_deleted", None, "gateway", data.gateway_id, None)
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "gateway_hard_deleted", "gateway_id": data.gateway_id}

class FactoryResetRequest(BaseModel):
    wait_for_device_confirmation: bool = True

def _clear_device_registry_links(cur, device_type: str, target_id: str, org_id: int | None):
    """Clears org/site/crypto links for a device being wiped (factory reset), so it can be
    resold or reprovisioned from a clean slate. Deliberately more aggressive than
    /devices/{serial}/deprovision, which intentionally leaves org_id/site_id in place for
    same-org redeployment continuity — factory reset means the device itself is being
    wiped, so the registry should match that."""
    if device_type == "gateway":
        cur.execute(
            "UPDATE gateways SET is_active = FALSE, org_id = NULL, site_id = NULL, crypto_id = NULL WHERE gateway_id = %s;",
            (target_id,),
        )
    else:
        cur.execute(
            "UPDATE sensors SET is_active = FALSE, org_id = NULL, site_id = NULL WHERE sensor_id = %s;",
            (target_id,),
        )
    cur.execute(
        "UPDATE device_registry SET is_provisioned = FALSE, provisioned_at = NULL WHERE serial_number = %s;",
        (target_id,),
    )

@app.post("/devices/{serial_number}/factory_reset")
def factory_reset_device(serial_number: str, data: FactoryResetRequest = FactoryResetRequest(), current_user: User = Depends(get_current_user)):
    """Sends a factory_reset command via ota_jobs (job_type='factory_reset', migration_004).
    Caller chooses per-request whether to wait for the device to confirm:
      - wait_for_device_confirmation=True (default): links are cleared only once the device
        reports success back via /ota/jobs/update — safer, avoids the registry saying
        "unlinked" before the physical device has actually wiped.
      - wait_for_device_confirmation=False: links are cleared immediately when the command
        is sent, without waiting for the device."""
    conn = get_db(); cur = conn.cursor()
    device = get_device_org_and_site(cur, serial_number)
    if not device:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found")
    device_org_id, device_site_id = device
    require_device_admin(cur, current_user, device_org_id, device_site_id)

    cur.execute("SELECT device_type FROM device_registry WHERE serial_number = %s;", (serial_number,))
    reg_row = cur.fetchone()
    device_type = reg_row[0] if reg_row else None
    if device_type not in ("gateway", "sensor"):
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found in registry")

    confirmation_required = data.wait_for_device_confirmation
    status_value = "pending" if confirmation_required else "success"
    cur.execute(
        """
        INSERT INTO ota_jobs (target_type, target_id, job_type, confirmation_required, status,
                               started_at, completed_at)
        VALUES (%s, %s, 'factory_reset', %s, %s, NOW(), CASE WHEN %s THEN NULL ELSE NOW() END)
        RETURNING ota_id;
        """,
        (device_type, serial_number, confirmation_required, status_value, confirmation_required),
    )
    ota_id = cur.fetchone()[0]

    table = "gateways" if device_type == "gateway" else "sensors"
    id_col = "gateway_id" if device_type == "gateway" else "sensor_id"
    cur.execute(f"UPDATE {table} SET ota_status = 'pending' WHERE {id_col} = %s;", (serial_number,))

    if confirmation_required:
        conn.commit(); cur.close(); conn.close()
        return {"status": "factory_reset_queued", "ota_id": ota_id, "confirmation_required": True}

    _clear_device_registry_links(cur, device_type, serial_number, device_org_id)
    log_event(cur, device_org_id, "device_factory_reset", current_user.user_id,
              device_type, serial_number, {"confirmation_required": False, "ota_id": ota_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "factory_reset_completed", "ota_id": ota_id, "confirmation_required": False}


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
    conn = get_db()
    cur = conn.cursor()
    require_org_admin(cur, current_user)  # Global Admin only for now, per your instruction — revisit site-scoping later

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

    log_event(cur, current_user.org_id, "ota_job_created", current_user.user_id, data.target_type, data.target_id,
              {"ota_id": ota_id, "firmware_version": data.firmware_version})
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
        SELECT j.ota_id, j.target_type, j.target_id, j.firmware_version, j.job_type, j.payload
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

    # job_type/payload are additive fields (migration_004). Existing firmware that only
    # reads firmware_version and target_type is unaffected for firmware_update jobs.
    # Firmware doesn't yet act on factory_reset/configuration_update job_types — those
    # will just sit here inertly (safe no-op) until firmware is updated to handle them.
    jobs = [
        {
            "ota_id": ota_id,
            "target_type": target_type,
            "target_id": target_id,
            "firmware_version": fw,
            "job_type": job_type,
            "payload": payload,
        }
        for ota_id, target_type, target_id, fw, job_type, payload in rows
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
        "SELECT target_type, target_id, firmware_version, job_type FROM ota_jobs WHERE ota_id = %s;",
        (data.ota_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.commit()
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="OTA job not found")

    target_type, target_id, firmware_version, job_type = row

    # Resolved before any status-specific update below, since the factory_reset success
    # path (further down) clears the device's org_id link as part of the wipe — looking
    # this up afterwards would find nothing to log against.
    if target_type == "gateway":
        cur.execute("SELECT org_id FROM gateways WHERE gateway_id = %s;", (target_id,))
    else:
        cur.execute("SELECT org_id FROM sensors WHERE sensor_id = %s;", (target_id,))
    ota_org_row = cur.fetchone()
    ota_org_id = ota_org_row[0] if ota_org_row else None

    # Update target firmware + ota_status
    if data.status == "success":
        if job_type == "firmware_update":
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
        elif job_type == "factory_reset":
            # This is the confirmation path from API-4: only clear links once the device
            # has actually confirmed the wipe, per wait_for_device_confirmation=True.
            device = get_device_org_and_site(cur, target_id)
            reset_org_id = device[0] if device else None
            _clear_device_registry_links(cur, target_type, target_id, reset_org_id)
            if reset_org_id:
                log_event(cur, reset_org_id, "device_factory_reset", None, target_type, target_id,
                           {"confirmation_required": True, "ota_id": data.ota_id})
        else:
            # configuration_update and any future job_type: mark success, no side effects yet.
            table = "gateways" if target_type == "gateway" else "sensors"
            id_col = "gateway_id" if target_type == "gateway" else "sensor_id"
            cur.execute(f"UPDATE {table} SET ota_status = 'success' WHERE {id_col} = %s;", (target_id,))
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

    if ota_org_id is not None:
        log_event(cur, ota_org_id, "ota_job_updated", None, target_type, target_id,
                  {"ota_id": data.ota_id, "status": data.status, "job_type": job_type})

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ota_job_updated", "ota_id": data.ota_id}


# =====================================================================================
# Phase B — Registry-first device provisioning
# =====================================================================================
# ASSUMPTION FLAGGED: gateways.gateway_id / sensors.sensor_id are separate text PKs from
# serial_number in the schema, but nothing in the provisioning spec says what a freshly
# manufactured device's gateway_id/sensor_id *is* before it's provisioned. I'm using
# serial_number as the gateway_id/sensor_id at provisioning time (i.e. they're the same
# string) since that's the only identifier device_registry actually gives us. If your
# firmware assigns its own separate gateway_id/sensor_id at boot, this needs revisiting —
# the simulator (simulator/sim.py) also still uses made-up ids ("gw1"/"room1") rather than
# real serials, so it'll need updating to match whatever we land on here.

class ProvisionDevice(BaseModel):
    serial_number: str
    site_id: int
    name: str | None = None
    location: str | None = None          # used for sensors only
    node_template_id: int | None = None  # optional: seed alert_rules from its alert_template

@app.post("/provisioning/activate")
# Serves BOTH the QR-quick-provision flow and the manual provisioning form — per the spec
# they differ only in how the frontend collects serial_number/site_id, not in what happens
# server-side, so one endpoint covers both.
def activate_device(data: ProvisionDevice, current_user: User = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    require_site_access(cur, current_user, current_user.org_id, data.site_id, admin=True)

    cur.execute(
        "SELECT device_type, is_provisioned FROM device_registry WHERE serial_number = %s;",
        (data.serial_number,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Serial number not found in device registry")
    device_type, is_provisioned = row
    if is_provisioned:
        existing = get_device_org_and_site(cur, data.serial_number)
        same_org = existing is not None and existing[0] == current_user.org_id
        cur.close(); conn.close()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_provisioned",
                "message": "Node serial number already exists, please deprovision it (delete it) and try again.",
                "same_org": same_org,
                # same_org=False is the "possible theft" signal per your instruction — the
                # device is provisioned somewhere, but not in the caller's own org. We don't
                # reveal which org it belongs to, just that it isn't this one.
            },
        )

    device_id = data.serial_number  # see assumption note above

    if device_type == "gateway":
        cur.execute(
            """
            INSERT INTO gateways (gateway_id, org_id, site_id, serial_number, name, is_active)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (gateway_id) DO UPDATE
            SET org_id = EXCLUDED.org_id, site_id = EXCLUDED.site_id,
                serial_number = EXCLUDED.serial_number, name = EXCLUDED.name, is_active = TRUE;
            """,
            (device_id, current_user.org_id, data.site_id, data.serial_number, data.name),
        )
    elif device_type == "sensor":
        cur.execute(
            """
            INSERT INTO sensors (sensor_id, org_id, site_id, serial_number, name, location, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (sensor_id) DO UPDATE
            SET org_id = EXCLUDED.org_id, site_id = EXCLUDED.site_id,
                serial_number = EXCLUDED.serial_number, name = EXCLUDED.name,
                location = EXCLUDED.location, is_active = TRUE;
            """,
            (device_id, current_user.org_id, data.site_id, data.serial_number, data.name, data.location),
        )
    else:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail=f"Unknown device_type '{device_type}' in registry")

    cur.execute(
        "UPDATE device_registry SET is_provisioned = TRUE, provisioned_at = NOW() WHERE serial_number = %s;",
        (data.serial_number,),
    )

    # Optional: seed alert_rules + default battery_profile_id for this device from its node_template
    if data.node_template_id is not None:
        cur.execute(
            "SELECT alert_template_id, battery_profile_id FROM node_templates WHERE node_template_id = %s AND org_id = %s;",
            (data.node_template_id, current_user.org_id),
        )
        nt_row = cur.fetchone()
        if not nt_row:
            cur.close(); conn.close()
            raise HTTPException(status_code=404, detail="Node template not found")
        alert_template_id, template_battery_profile_id = nt_row
        if template_battery_profile_id is not None:
            table = "gateways" if device_type == "gateway" else "sensors"
            id_col = "gateway_id" if device_type == "gateway" else "sensor_id"
            cur.execute(
                f"UPDATE {table} SET battery_profile_id = %s WHERE {id_col} = %s;",
                (template_battery_profile_id, device_id),
            )
        if alert_template_id is not None:
            cur.execute(
                "SELECT metric_name, threshold_min, threshold_max, trigger_value FROM alert_template_rules WHERE alert_template_id = %s;",
                (alert_template_id,),
            )
            for metric_name, tmin, tmax, trigger_value in cur.fetchall():
                cur.execute(
                    """
                    INSERT INTO alert_rules (serial_number, metric_name, threshold_min, threshold_max, trigger_value, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (serial_number, metric_name) WHERE is_active = TRUE DO NOTHING;
                    """,
                    (data.serial_number, metric_name, tmin, tmax, trigger_value, current_user.user_id),
                )

    log_event(cur, current_user.org_id, "device_provisioned", current_user.user_id,
              device_type, data.serial_number, {"site_id": data.site_id})

    conn.commit()
    cur.close()
    conn.close()
    return {"status": "provisioned", "serial_number": data.serial_number, "device_type": device_type}

@app.get("/provisioning/check")
def check_device(serial_number: str, current_user: User = Depends(get_current_user)):
    """Read-only pre-flight check for the QR-scan/manual-provisioning form, so the
    frontend can show a useful message BEFORE committing to /provisioning/activate
    (which mutates). Doesn't require org/site access to the device — checking a serial
    doesn't touch anything, it's the same "is this legit or possibly stolen" question a
    person scanning a found/purchased device needs answered regardless of role."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT device_type, is_provisioned FROM device_registry WHERE serial_number = %s;", (serial_number,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return {"status": "not_found"}
    device_type, is_provisioned = row
    if not is_provisioned:
        cur.close(); conn.close()
        return {"status": "available", "device_type": device_type}
    existing = get_device_org_and_site(cur, serial_number)
    same_org = existing is not None and existing[0] == current_user.org_id
    cur.close(); conn.close()
    return {"status": "already_provisioned", "device_type": device_type, "same_org": same_org}

@app.post("/devices/{serial_number}/deprovision")
def deprovision_device(serial_number: str, current_user: User = Depends(get_current_user)):
    """The other half of the "already provisioned" error message — lets an admin actually
    act on it for a legitimate redeployment. Deactivates the gateway/sensor row and clears
    device_registry.is_provisioned so the serial becomes available to /provisioning/activate
    again (a fresh activation will overwrite org_id/site_id via its ON CONFLICT DO UPDATE).
    Logged, since this is exactly the kind of action worth an audit trail if a device
    later turns out to have been stolen rather than legitimately redeployed."""
    conn = get_db(); cur = conn.cursor()
    device = get_device_org_and_site(cur, serial_number)
    if not device:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found or not currently provisioned")
    device_org_id, device_site_id = device
    require_device_admin(cur, current_user, device_org_id, device_site_id)

    cur.execute("SELECT device_type FROM device_registry WHERE serial_number = %s;", (serial_number,))
    reg_row = cur.fetchone()
    device_type = reg_row[0] if reg_row else None
    if device_type == "gateway":
        cur.execute("UPDATE gateways SET is_active = FALSE WHERE gateway_id = %s;", (serial_number,))
    elif device_type == "sensor":
        cur.execute("UPDATE sensors SET is_active = FALSE WHERE sensor_id = %s;", (serial_number,))

    cur.execute(
        "UPDATE device_registry SET is_provisioned = FALSE, provisioned_at = NULL WHERE serial_number = %s;",
        (serial_number,),
    )
    log_event(cur, device_org_id, "device_deprovisioned", current_user.user_id,
              device_type or "device", serial_number, {"previous_site_id": device_site_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "deprovisioned", "serial_number": serial_number}

# Batch QR-photo import (deferred per outstanding-tasks doc — not building this pass).


# =====================================================================================
# Phase C — Alert evaluation logic
# =====================================================================================
# DECISION MADE (flagging, not asking): evaluating synchronously inside /ingest rather
# than a separate job. At current/expected prototype scale there's no queue/worker
# infrastructure in docker-compose.yml, and doing it inline keeps the demo simple with
# no extra moving parts. Revisit if ingest volume ever makes this a bottleneck.
#
# battery is evaluated as raw voltage (matches the schema decision that %-conversion is a
# frontend-only concern). motion is boolean and doesn't fit the min/max threshold model
# alert_rules uses — not evaluated here; a boolean-trigger rule type would need its own
# schema support, flagging as a gap rather than silently faking it.

def resolve_serial_number(cur, gateway_id: str | None, sensor_id: str | None) -> str | None:
    if sensor_id:
        cur.execute("SELECT serial_number FROM sensors WHERE sensor_id = %s;", (sensor_id,))
        row = cur.fetchone()
        if row and row[0]:
            return row[0]
    if gateway_id:
        cur.execute("SELECT serial_number FROM gateways WHERE gateway_id = %s;", (gateway_id,))
        row = cur.fetchone()
        if row:
            return row[0]
    return None

def evaluate_alert_rules(cur, serial_number: str, readings: dict):
    """readings values may be float (numeric metrics, checked against threshold_min/max) or
    bool (boolean metrics like motion, checked against trigger_value). Requires
    db_migration_002.sql (adds alert_rules.trigger_value) to have been applied."""
    for metric_name, value in readings.items():
        if value is None:
            continue
        cur.execute(
            """
            SELECT alert_rule_id, threshold_min, threshold_max, trigger_value
            FROM alert_rules
            WHERE serial_number = %s AND metric_name = %s AND is_active = TRUE;
            """,
            (serial_number, metric_name),
        )
        rule = cur.fetchone()
        if not rule:
            continue
        alert_rule_id, tmin, tmax, trigger_value = rule
        if isinstance(value, bool):  # check bool before number — bool is a subclass of int in Python
            breached = trigger_value is not None and value == trigger_value
        else:
            breached = (tmin is not None and value < tmin) or (tmax is not None and value > tmax)
        if not breached:
            continue
        cur.execute("SELECT 1 FROM alerts WHERE alert_rule_id = %s AND status = 'open';", (alert_rule_id,))
        if cur.fetchone():
            continue  # already an open alert for this rule — don't spam duplicates
        # triggered_value is double precision — booleans are stored as 1.0/0.0
        stored_value = (1.0 if value else 0.0) if isinstance(value, bool) else value
        cur.execute(
            """
            INSERT INTO alerts (alert_rule_id, serial_number, metric_name, triggered_value)
            VALUES (%s, %s, %s, %s);
            """,
            (alert_rule_id, serial_number, metric_name, stored_value),
        )


# =====================================================================================
# Phase D — Backup system
# =====================================================================================
# SCOPE LIMITATION FLAGGED: only tables with a direct org_id column are covered here
# (sites, gateways, sensors, node_templates, alert_templates, crypto_profiles).
# sensor_capabilities, alert_rules, alert_template_rules and user_site_roles don't carry
# org_id directly (they hang off sensor_id/serial_number/alert_template_id/user_id), so
# they're NOT in this backup's scope yet — they'd need join-based extraction. Flagging
# this as a real gap rather than quietly shipping a partial backup as if it were complete.
#
# SCHEDULING FLAGGED: nothing in docker-compose.yml runs periodic jobs (no cron container,
# no APScheduler in the api service). The functions below (run_scheduled_backup,
# prune_org_backups, cleanup_orphaned_snapshots, run_weekly_fallback_backup) are ready to
# be called by a scheduler, but nothing calls them automatically yet — that's an
# infrastructure piece (e.g. an APScheduler thread in main.py, or a separate cron service)
# that needs a decision on your end before it's "actually running" rather than "callable".

from jobs import (
    BACKUP_TABLES, RESTORE_PK, compute_row_hash, snapshot_org_data,
    prune_org_backups, cleanup_orphaned_snapshots, run_scheduled_backup,
    run_weekly_fallback_backup, run_gdpr_deletion_sweep,
)

# =====================================================================================
# Scheduler manual override (API-6)
# =====================================================================================
# The `scheduler` service is a separate long-running process (api/scheduler.py, its own
# container) -- this endpoint doesn't talk to it over IPC. It imports the same module
# (same image, same api/ directory) and calls the job function directly against the DB,
# independent of whatever the actual BlockingScheduler process is doing. Good enough for
# "ops needs to force a job to run right now" without building a job queue.

class SchedulerRunRequest(BaseModel):
    job_id: str  # one of scheduler.JOBS' keys, e.g. 'daily_backup', 'gdpr_sweep'

@app.post("/scheduler/run")
def run_scheduler_job_now(data: SchedulerRunRequest, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.close(); conn.close()
    import scheduler as scheduler_module
    try:
        scheduler_module.run_job_now(data.job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "job_run_triggered", "job_id": data.job_id}

class BackupCreate(BaseModel):
    name: str
    description: str | None = None

@app.post("/backups/create")
def create_backup(data: BackupCreate, current_user: User = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute(
        """
        INSERT INTO backups (org_id, name, description, schedule_type, status, started_at, created_by)
        VALUES (%s, %s, %s, 'manual', 'in_progress', NOW(), %s)
        RETURNING backup_id;
        """,
        (current_user.org_id, data.name, data.description, current_user.user_id),
    )
    backup_id = cur.fetchone()[0]
    try:
        snapshot_org_data(cur, current_user.org_id, backup_id)
        cur.execute("UPDATE backups SET status = 'completed', completed_at = NOW() WHERE backup_id = %s;", (backup_id,))
        log_event(cur, current_user.org_id, "backup_created", current_user.user_id, "backup", str(backup_id), {"name": data.name})
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.execute("UPDATE backups SET status = 'failed', error_message = %s WHERE backup_id = %s;", (str(e), backup_id))
        conn.commit()
        cur.close(); conn.close()
        raise HTTPException(status_code=500, detail="Backup failed")
    cur.close(); conn.close()
    return {"status": "backup_completed", "backup_id": backup_id}

@app.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    require_org_admin(cur, current_user)

    cur.execute("SELECT org_id FROM backups WHERE backup_id = %s;", (backup_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Backup not found")
    if row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=403, detail="Backup belongs to another organisation")

    link_tbl = f"backup_snapshot_links_org_{current_user.org_id}"
    data_tbl = f"backup_snapshot_data_org_{current_user.org_id}"
    cur.execute(
        f"""
        SELECT d.source_table, d.row_data
        FROM {link_tbl} l JOIN {data_tbl} d ON l.snapshot_data_id = d.snapshot_data_id
        WHERE l.backup_id = %s;
        """,
        (backup_id,),
    )
    restored = 0
    for source_table, row_data in cur.fetchall():
        pk_col = RESTORE_PK.get(source_table)
        if not pk_col:
            continue
        cols = list(row_data.keys())
        vals = [row_data[c] for c in cols]
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != pk_col)
        col_list = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        cur.execute(
            f"INSERT INTO {source_table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({pk_col}) DO UPDATE SET {set_clause};",
            vals,
        )
        restored += 1

    log_event(cur, current_user.org_id, "backup_restored", current_user.user_id, "backup", str(backup_id), {"rows_restored": restored})
    conn.commit()
    cur.close(); conn.close()
    return {"status": "restored", "backup_id": backup_id, "rows_restored": restored}

class BackupSettingsUpdate(BaseModel):
    is_enabled: bool | None = None
    daily_retention_count: int | None = None
    weekly_retention_count: int | None = None
    monthly_retention_count: int | None = None

@app.get("/backups/settings")
def get_backup_settings(current_user: User = Depends(get_current_user)):
    """Outstanding-tasks item #6: POST (set) has existed since the backup system shipped,
    but nothing read current values back — the Settings -> Backups tab's settings form
    could only write, never show what's actually configured. Returns defaults (matching
    the table's own column defaults) if the org has never saved settings yet, rather than
    a 404 — "not configured yet" isn't an error state."""
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute(
        """
        SELECT is_enabled, daily_retention_count, weekly_retention_count, monthly_retention_count, updated_at
        FROM org_backup_settings WHERE org_id = %s;
        """,
        (current_user.org_id,),
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return {
            "is_enabled": False, "daily_retention_count": 7, "weekly_retention_count": 4,
            "monthly_retention_count": 3, "updated_at": None, "configured": False,
        }
    return {
        "is_enabled": row[0], "daily_retention_count": row[1], "weekly_retention_count": row[2],
        "monthly_retention_count": row[3], "updated_at": row[4].isoformat() if row[4] else None,
        "configured": True,
    }

@app.post("/backups/settings")
def update_backup_settings(data: BackupSettingsUpdate, current_user: User = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    require_org_admin(cur, current_user)  # Global Admin only, per spec

    cur.execute(
        """
        UPDATE org_backup_settings SET
            is_enabled = COALESCE(%s, is_enabled),
            daily_retention_count = COALESCE(%s, daily_retention_count),
            weekly_retention_count = COALESCE(%s, weekly_retention_count),
            monthly_retention_count = COALESCE(%s, monthly_retention_count),
            updated_by = %s, updated_at = NOW()
        WHERE org_id = %s;
        """,
        (data.is_enabled, data.daily_retention_count, data.weekly_retention_count,
         data.monthly_retention_count, current_user.user_id, current_user.org_id),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO org_backup_settings (org_id, is_enabled, daily_retention_count,
                weekly_retention_count, monthly_retention_count, updated_by)
            VALUES (%s, COALESCE(%s, FALSE), COALESCE(%s, 7), COALESCE(%s, 4), COALESCE(%s, 3), %s);
            """,
            (current_user.org_id, data.is_enabled, data.daily_retention_count,
             data.weekly_retention_count, data.monthly_retention_count, current_user.user_id),
        )
    log_event(cur, current_user.org_id, "backup_settings_updated", current_user.user_id, "organisation", str(current_user.org_id),
              {"is_enabled": data.is_enabled, "daily_retention_count": data.daily_retention_count,
               "weekly_retention_count": data.weekly_retention_count, "monthly_retention_count": data.monthly_retention_count})
    conn.commit()
    cur.close(); conn.close()
    return {"status": "backup_settings_updated"}

@app.get("/backups")
def list_backups(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)  # Global Admin only, per spec — matches /backups/create
    cur.execute(
        """
        SELECT backup_id, name, description, schedule_type, status, started_at, completed_at,
               error_message, created_by, created_at
        FROM backups
        WHERE org_id = %s
        ORDER BY created_at DESC;
        """,
        (current_user.org_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"backups": [
        {"backup_id": r[0], "name": r[1], "description": r[2], "schedule_type": r[3], "status": r[4],
         "started_at": r[5], "completed_at": r[6], "error_message": r[7], "created_by": r[8], "created_at": r[9]}
        for r in rows
    ]}

# =====================================================================================
# Phase E — GDPR deletion
# =====================================================================================

def count_global_admins(cur, org_id: int) -> int:
    cur.execute(
        """
        SELECT COUNT(*) FROM user_site_roles usr
        JOIN users u ON u.user_id = usr.user_id
        WHERE usr.site_id IS NULL AND usr.role = 'global_admin' AND u.org_id = %s;
        """,
        (org_id,),
    )
    return cur.fetchone()[0]

@app.post("/organisations/gdpr_delete/request")
def request_org_deletion(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)

    if count_global_admins(cur, current_user.org_id) > 1:
        cur.close(); conn.close()
        raise HTTPException(
            status_code=400,
            detail="Other Global Admins exist for this organisation — use self-delete instead, "
                   "or remove/demote the other admins first.",
        )

    cur.execute("SELECT 1 FROM gdpr_deletion_requests WHERE org_id = %s AND status = 'pending';", (current_user.org_id,))
    if cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="A deletion request is already pending for this organisation")

    cancel_token = str(uuid.uuid4())
    scheduled_for = datetime.utcnow() + timedelta(days=14)
    cur.execute(
        """
        INSERT INTO gdpr_deletion_requests (org_id, requested_by, scheduled_for, cancel_token)
        VALUES (%s, %s, %s, %s)
        RETURNING gdpr_deletion_request_id;
        """,
        (current_user.org_id, current_user.user_id, scheduled_for, cancel_token),
    )
    request_id = cur.fetchone()[0]
    log_event(cur, current_user.org_id, "org_deletion_requested", current_user.user_id,
              "organisation", str(current_user.org_id), {"scheduled_for": scheduled_for.isoformat()})
    conn.commit()
    cur.close(); conn.close()

    cancel_url = FRONTEND_BASE_URL + f"/gdpr-cancel?token={cancel_token}"
    send_templated_email(
        current_user.email, "WatchDog organisation deletion scheduled",
        f"Your organisation's data is scheduled for deletion on {scheduled_for}.\n"
        f"To cancel, visit:\n{cancel_url}",
    )
    print(f"[DEBUG] Org deletion scheduled for {scheduled_for}. Cancel: {cancel_url}")
    return {"status": "deletion_scheduled", "scheduled_for": scheduled_for.isoformat(), "gdpr_deletion_request_id": request_id}

@app.post("/organisations/gdpr_delete/cancel")
def cancel_org_deletion(token: str, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT gdpr_deletion_request_id, org_id, status FROM gdpr_deletion_requests WHERE cancel_token = %s;",
        (token,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Invalid cancellation link")
    req_id, org_id, status_ = row
    if org_id != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=403, detail="This request belongs to another organisation")
    if status_ != "pending":
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail=f"Request is already {status_}")

    cur.execute(
        "UPDATE gdpr_deletion_requests SET status = 'cancelled', cancelled_by = %s, cancelled_at = NOW() WHERE gdpr_deletion_request_id = %s;",
        (current_user.user_id, req_id),
    )
    log_event(cur, current_user.org_id, "org_deletion_cancelled", current_user.user_id, "organisation", str(current_user.org_id), None)
    conn.commit()
    cur.close(); conn.close()
    return {"status": "cancelled"}

@app.post("/users/me/self_delete/request")
def request_self_delete(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    if get_global_role(cur, current_user.user_id) == "global_admin" and count_global_admins(cur, current_user.org_id) <= 1:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="You are the last Global Admin — request organisation deletion instead")

    token = create_verification_token(cur, current_user.user_id, "account_deletion")
    log_event(cur, current_user.org_id, "self_delete_requested", current_user.user_id, "user", str(current_user.user_id), None)
    conn.commit(); cur.close(); conn.close()

    confirm_url = FRONTEND_BASE_URL + f"/confirm-delete?token={token}"
    send_templated_email(
        current_user.email, "Confirm your WatchDog account deletion",
        f"Confirm deletion of your WatchDog account by visiting:\n{confirm_url}\n\nThis link expires in 24 hours.",
    )
    print(f"[DEBUG] Send self-delete confirmation to {current_user.email}: {confirm_url}")
    return {"status": "confirmation_sent"}

@app.post("/users/me/self_delete/confirm")
def confirm_self_delete(token: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT token_id, user_id, expires_at, used_at FROM user_verification_tokens WHERE token = %s AND reason = 'account_deletion';",
        (token,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Invalid token")
    token_id, user_id, expires_at, used_at = row
    if used_at is not None or datetime.utcnow() > expires_at:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Token expired or already used")

    cur.execute("UPDATE user_verification_tokens SET used_at = NOW() WHERE token_id = %s;", (token_id,))
    cur.execute("SELECT org_id FROM users WHERE user_id = %s;", (user_id,))
    self_delete_org_row = cur.fetchone()
    cur.execute("SELECT hard_delete_user(%s);", (user_id,))
    if self_delete_org_row:
        log_event(cur, self_delete_org_row[0], "user_self_deleted", None, "user", str(user_id), None)
    conn.commit()
    cur.close(); conn.close()
    return {"status": "account_deleted"}

@app.post("/users/{target_user_id}/admin_delete")
def admin_delete_user(target_user_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id FROM users WHERE user_id = %s;", (target_user_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    authorize_admin_action_on_user(cur, current_user, target_user_id, row[0], rank_relation="strict")

    cur.execute("SELECT hard_delete_user(%s);", (target_user_id,))
    log_event(cur, current_user.org_id, "user_deleted", current_user.user_id, "user", str(target_user_id), None)
    conn.commit()
    cur.close(); conn.close()
    return {"status": "user_deleted", "user_id": target_user_id}


# =====================================================================================
# Phase F — Lock / Suspend
# =====================================================================================
# Lock requires the actor to strictly outrank the target (spec: "higher-ranked admin").
# Suspend allows same-or-lower rank (spec explicitly says "same-or-lower rank"), plus
# self-suspend. Both now use real role_hierarchy.rank values via get_user_best_rank().
#
# DO NOT DELETE - Claude needs this to see the role_hierachy (stored inside the database table):
#   Role, Rank (higher means more power)
#   ----------
#   global_admin, 4
#   site_admin, 3
#   global_viewer, 2
#   site_viewer, 1
#   no_access, 0

@app.post("/users/{target_user_id}/lock")
def lock_user(target_user_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id FROM users WHERE user_id = %s;", (target_user_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    authorize_admin_action_on_user(cur, current_user, target_user_id, row[0], rank_relation="strict")

    cur.execute(
        """
        UPDATE users SET is_locked = TRUE, locked_at = NOW(), locked_by = %s,
            sessions_invalidated_at = NOW()
        WHERE user_id = %s;
        """,
        (current_user.user_id, target_user_id),
    )
    log_event(cur, current_user.org_id, "user_locked", current_user.user_id, "user", str(target_user_id), None)
    conn.commit()
    cur.close(); conn.close()
    return {"status": "user_locked", "user_id": target_user_id}

@app.post("/users/unlock/request")
def request_unlock(email: str):
    """Always returns success regardless of whether the email exists/is locked, to avoid
    leaking account existence."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT user_id, org_id FROM users WHERE email = %s AND is_locked = TRUE;", (email,))
    row = cur.fetchone()
    if row:
        token = create_verification_token(cur, row[0], "account_unlock")
        log_event(cur, row[1], "user_unlock_requested", None, "user", str(row[0]), None)
        conn.commit()
        unlock_url = FRONTEND_BASE_URL + f"/unlock?token={token}"
        send_templated_email(
            email, "Unlock your WatchDog account",
            f"Unlock your WatchDog account by visiting:\n{unlock_url}\n\nThis link expires in 24 hours.",
        )
        print(f"[DEBUG] Send unlock/password-reset email to {email}: {unlock_url}")
    cur.close(); conn.close()
    return {"status": "if_locked_email_sent"}

class UnlockConfirm(BaseModel):
    token: str
    new_password: str

@app.post("/users/unlock/confirm")
def confirm_unlock(data: UnlockConfirm):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT token_id, user_id, expires_at, used_at FROM user_verification_tokens WHERE token = %s AND reason = 'account_unlock';",
        (data.token,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Invalid token")
    token_id, user_id, expires_at, used_at = row
    if used_at is not None or datetime.utcnow() > expires_at:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Token expired or already used")
    if len(data.new_password) < 8:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    new_hash = get_password_hash(data.new_password)
    cur.execute(
        "UPDATE users SET password_hash = %s, is_locked = FALSE, locked_at = NULL, locked_by = NULL WHERE user_id = %s RETURNING org_id;",
        (new_hash, user_id),
    )
    unlock_org_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO user_auth_methods (user_id, method_type) VALUES (%s, 'password') "
        "ON CONFLICT (user_id, method_type) DO NOTHING;",
        (user_id,),
    )
    cur.execute("UPDATE user_verification_tokens SET used_at = NOW() WHERE token_id = %s;", (token_id,))
    log_event(cur, unlock_org_id, "user_unlock_confirmed", None, "user", str(user_id), None)
    conn.commit()
    cur.close(); conn.close()
    return {"status": "unlocked"}

class SuspendUser(BaseModel):
    reason: str | None = None

@app.post("/users/{target_user_id}/suspend")
def suspend_user(target_user_id: int, data: SuspendUser, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id FROM users WHERE user_id = %s;", (target_user_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    target_org_id = row[0]

    is_self = target_user_id == current_user.user_id
    if not is_self:
        authorize_admin_action_on_user(cur, current_user, target_user_id, target_org_id, rank_relation="gte")

    cur.execute(
        """
        UPDATE users SET is_suspended = TRUE, suspended_at = NOW(), suspended_by = %s,
            suspend_reason = %s, sessions_invalidated_at = NOW()
        WHERE user_id = %s;
        """,
        (current_user.user_id, data.reason, target_user_id),
    )
    log_event(cur, target_org_id, "user_suspended", current_user.user_id, "user", str(target_user_id),
              {"reason": data.reason, "self_triggered": is_self})
    conn.commit()
    cur.close(); conn.close()
    return {"status": "user_suspended", "user_id": target_user_id}

@app.post("/users/{target_user_id}/unsuspend")
def unsuspend_user(target_user_id: int, current_user: User = Depends(get_current_user)):
    # Deliberately not self-serve: self-suspend implies suspected compromise, so
    # un-suspending should require an admin, not the (possibly compromised) account itself.
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id FROM users WHERE user_id = %s;", (target_user_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    if row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=403, detail="User belongs to another organisation")
    require_org_admin(cur, current_user)

    cur.execute(
        "UPDATE users SET is_suspended = FALSE, suspended_at = NULL, suspended_by = NULL, suspend_reason = NULL WHERE user_id = %s;",
        (target_user_id,),
    )
    log_event(cur, current_user.org_id, "user_unsuspended", current_user.user_id, "user", str(target_user_id), None)
    conn.commit()
    cur.close(); conn.close()
    return {"status": "user_unsuspended", "user_id": target_user_id}


# =====================================================================================
# Sites CRUD
# =====================================================================================
# Creating/deleting a site is an org-structural action (spec: "Organisation Admins may
# also create multiple properties") -> Global Admin only. Editing an existing site is
# site-scoped (Global Admin or that site's Site Admin). Listing is filtered: global-role
# users see every site in the org, site-scoped users see only sites they hold a grant on.

class SiteCreate(BaseModel):
    name: str
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    postcode: str | None = None
    country: str | None = None

class SiteUpdate(BaseModel):
    name: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    postcode: str | None = None
    country: str | None = None
    is_active: bool | None = None

@app.post("/sites")
def create_site(data: SiteCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute(
        """
        INSERT INTO sites (org_id, name, address_line1, address_line2, city, postcode, country)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING site_id;
        """,
        (current_user.org_id, data.name, data.address_line1, data.address_line2,
         data.city, data.postcode, data.country),
    )
    site_id = cur.fetchone()[0]
    log_event(cur, current_user.org_id, "site_created", current_user.user_id, "site", str(site_id), {"name": data.name})
    conn.commit(); cur.close(); conn.close()
    return {"status": "site_created", "site_id": site_id}

@app.get("/sites")
def list_sites(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    if get_global_role(cur, current_user.user_id):
        cur.execute(
            "SELECT site_id, name, city, country, is_active FROM sites WHERE org_id = %s ORDER BY name;",
            (current_user.org_id,),
        )
    else:
        cur.execute(
            """
            SELECT s.site_id, s.name, s.city, s.country, s.is_active FROM sites s
            JOIN user_site_roles usr ON usr.site_id = s.site_id
            WHERE usr.user_id = %s ORDER BY s.name;
            """,
            (current_user.user_id,),
        )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"sites": [{"site_id": r[0], "name": r[1], "city": r[2], "country": r[3], "is_active": r[4]} for r in rows]}

@app.put("/sites/{site_id}")
def update_site(site_id: int, data: SiteUpdate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_site_access(cur, current_user, current_user.org_id, site_id, admin=True)
    fields, values = [], []
    for col in ("name", "address_line1", "address_line2", "city", "postcode", "country", "is_active"):
        v = getattr(data, col)
        if v is not None:
            fields.append(f"{col} = %s")
            values.append(v)
    if fields:
        values.append(site_id)
        cur.execute(f"UPDATE sites SET {', '.join(fields)} WHERE site_id = %s;", values)
    log_event(cur, current_user.org_id, "site_edited", current_user.user_id, "site", str(site_id), None)
    conn.commit(); cur.close(); conn.close()
    return {"status": "site_updated", "site_id": site_id}

@app.delete("/sites/{site_id}")
def delete_site(site_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute("UPDATE sites SET is_active = FALSE WHERE site_id = %s AND org_id = %s;", (site_id, current_user.org_id))
    log_event(cur, current_user.org_id, "site_deleted", current_user.user_id, "site", str(site_id), None)
    conn.commit(); cur.close(); conn.close()
    return {"status": "site_deleted", "site_id": site_id}


# =====================================================================================
# Node Templates CRUD
# =====================================================================================
# Global Admin only for now, matching the other new-resource creation in this pass.

class NodeTemplateCreate(BaseModel):
    name: str
    device_type: str  # 'gateway' or 'sensor'
    mcu_variant_id: int
    cloud_service_url: str | None = None
    comms_interfaces: str | None = None
    sleep_time_seconds: int | None = None
    polling_interval_seconds: int | None = None
    wlan_crypto_id: int | None = None
    mesh_crypto_id: int | None = None
    packet_crypto_id: int | None = None
    alert_template_id: int | None = None
    battery_profile_id: int | None = None  # default battery type this template's devices are provisioned with

def validate_node_template(data: NodeTemplateCreate):
    if data.device_type not in ("gateway", "sensor"):
        raise HTTPException(status_code=400, detail="device_type must be 'gateway' or 'sensor'")
    # Validation gap closed: cloud_service_url only makes sense for gateway/root nodes.
    if data.device_type == "sensor" and data.cloud_service_url is not None:
        raise HTTPException(
            status_code=400,
            detail="cloud_service_url must be omitted for sensor templates — only Root/Gateway nodes bind to the cloud service",
        )

@app.post("/node_templates")
def create_node_template(data: NodeTemplateCreate, current_user: User = Depends(get_current_user)):
    validate_node_template(data)
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute(
        """
        INSERT INTO node_templates (org_id, name, device_type, mcu_variant_id, cloud_service_url,
            comms_interfaces, sleep_time_seconds, polling_interval_seconds,
            wlan_crypto_id, mesh_crypto_id, packet_crypto_id, alert_template_id, battery_profile_id, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING node_template_id;
        """,
        (current_user.org_id, data.name, data.device_type, data.mcu_variant_id, data.cloud_service_url,
         data.comms_interfaces, data.sleep_time_seconds, data.polling_interval_seconds,
         data.wlan_crypto_id, data.mesh_crypto_id, data.packet_crypto_id, data.alert_template_id,
         data.battery_profile_id, current_user.user_id),
    )
    node_template_id = cur.fetchone()[0]
    log_event(cur, current_user.org_id, "node_template_created", current_user.user_id, "node_template",
              str(node_template_id), {"name": data.name, "device_type": data.device_type})
    conn.commit(); cur.close(); conn.close()
    return {"status": "node_template_created", "node_template_id": node_template_id}

@app.get("/node_templates")
def list_node_templates(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT node_template_id, name, device_type, mcu_variant_id, alert_template_id, battery_profile_id FROM node_templates WHERE org_id = %s ORDER BY name;",
        (current_user.org_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"node_templates": [
        {"node_template_id": r[0], "name": r[1], "device_type": r[2], "mcu_variant_id": r[3],
         "alert_template_id": r[4], "battery_profile_id": r[5]}
        for r in rows
    ]}

@app.delete("/node_templates/{node_template_id}")
def delete_node_template(node_template_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute("DELETE FROM node_templates WHERE node_template_id = %s AND org_id = %s;", (node_template_id, current_user.org_id))
    log_event(cur, current_user.org_id, "node_template_deleted", current_user.user_id, "node_template",
              str(node_template_id), None)
    conn.commit(); cur.close(); conn.close()
    return {"status": "node_template_deleted", "node_template_id": node_template_id}


# =====================================================================================
# Node Template — Sensor Module + GPIO pin assignment (nested editor)
# =====================================================================================
# Previously flagged as parked/not-built; built now as part of the WatchDog Employee
# Portal work, since sensor_module_types now needs somewhere for its entries to actually
# be *used* by an org, and the GPIO reserved/restricted validation you asked for has
# nowhere to live without this existing.

class ModulePinAssignmentCreate(BaseModel):
    module_type_id: int
    i2c_address_override: str | None = None

@app.post("/node_templates/{node_template_id}/module_pins")
def add_module_pin_assignment(node_template_id: int, data: ModulePinAssignmentCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id FROM node_templates WHERE node_template_id = %s;", (node_template_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Node template not found")
    if row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=403, detail="Node template belongs to another organisation")
    require_org_admin(cur, current_user)
    cur.execute(
        """
        INSERT INTO node_template_module_pins (node_template_id, module_type_id, i2c_address_override)
        VALUES (%s, %s, %s)
        ON CONFLICT (node_template_id, module_type_id) DO UPDATE SET i2c_address_override = EXCLUDED.i2c_address_override
        RETURNING node_template_module_pin_id;
        """,
        (node_template_id, data.module_type_id, data.i2c_address_override),
    )
    pin_id = cur.fetchone()[0]
    log_event(cur, current_user.org_id, "node_template_pin_added", current_user.user_id, "node_template_module_pin",
              str(pin_id), {"node_template_id": node_template_id, "module_type_id": data.module_type_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "module_pin_assigned", "node_template_module_pin_id": pin_id}

@app.get("/node_templates/{node_template_id}/module_pins")
def list_module_pin_assignments(node_template_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id FROM node_templates WHERE node_template_id = %s;", (node_template_id,))
    row = cur.fetchone()
    if not row or row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Node template not found")
    cur.execute(
        "SELECT node_template_module_pin_id, module_type_id, i2c_address_override FROM node_template_module_pins WHERE node_template_id = %s;",
        (node_template_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"module_pins": [
        {"node_template_module_pin_id": r[0], "module_type_id": r[1], "i2c_address_override": r[2]}
        for r in rows
    ]}

@app.delete("/node_templates/{node_template_id}/module_pins/{pin_id}")
def delete_module_pin_assignment(node_template_id: int, pin_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id FROM node_templates WHERE node_template_id = %s;", (node_template_id,))
    row = cur.fetchone()
    if not row or row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Node template not found")
    require_org_admin(cur, current_user)
    # ON DELETE CASCADE on node_template_module_gpio_pins cleans up any GPIO assignments too
    cur.execute(
        "DELETE FROM node_template_module_pins WHERE node_template_module_pin_id = %s AND node_template_id = %s;",
        (pin_id, node_template_id),
    )
    log_event(cur, current_user.org_id, "node_template_pin_removed", current_user.user_id, "node_template_module_pin",
              str(pin_id), {"node_template_id": node_template_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "module_pin_deleted", "node_template_module_pin_id": pin_id}

class GpioAssignmentCreate(BaseModel):
    pin_role: str
    gpio_pin: str

@app.post("/node_templates/module_pins/{pin_id}/gpio_pins")
def add_gpio_assignment(pin_id: int, data: GpioAssignmentCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    # Resolve org via node_template_module_pins -> node_templates, and mcu_variant_id via
    # node_templates -> mcu_variant_id, to validate the pin against that MCU's GPIO catalog.
    cur.execute(
        """
        SELECT nt.org_id, nt.mcu_variant_id
        FROM node_template_module_pins ntmp
        JOIN node_templates nt ON nt.node_template_id = ntmp.node_template_id
        WHERE ntmp.node_template_module_pin_id = %s;
        """,
        (pin_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Module pin assignment not found")
    org_id, mcu_variant_id = row
    if org_id != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=403, detail="Belongs to another organisation")
    require_org_admin(cur, current_user)

    # Validation gap closed: reject reserved/restricted pins for this MCU variant.
    cur.execute(
        "SELECT status FROM mcu_variant_gpio_pins WHERE mcu_variant_id = %s AND gpio_pin = %s;",
        (mcu_variant_id, data.gpio_pin),
    )
    pin_row = cur.fetchone()
    if pin_row and pin_row[0] in ("reserved", "restricted"):
        cur.close(); conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"GPIO pin '{data.gpio_pin}' is {pin_row[0]} on this MCU variant and cannot be assigned",
        )
    # NOTE: a pin with no row at all in mcu_variant_gpio_pins is allowed through — that
    # table isn't guaranteed to be exhaustively populated for every pin on every variant,
    # so "unlisted" is treated as "no constraint on record" rather than "forbidden".

    cur.execute(
        """
        INSERT INTO node_template_module_gpio_pins (node_template_module_pin_id, pin_role, gpio_pin)
        VALUES (%s, %s, %s)
        ON CONFLICT (node_template_module_pin_id, pin_role) DO UPDATE SET gpio_pin = EXCLUDED.gpio_pin
        RETURNING node_template_module_gpio_pin_id;
        """,
        (pin_id, data.pin_role, data.gpio_pin),
    )
    gpio_assignment_id = cur.fetchone()[0]
    log_event(cur, org_id, "node_template_gpio_assigned", current_user.user_id, "node_template_module_gpio_pin",
              str(gpio_assignment_id), {"pin_id": pin_id, "pin_role": data.pin_role, "gpio_pin": data.gpio_pin})
    conn.commit(); cur.close(); conn.close()
    return {"status": "gpio_assigned", "node_template_module_gpio_pin_id": gpio_assignment_id}

@app.get("/node_templates/module_pins/{pin_id}/gpio_pins")
def list_gpio_assignments(pin_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        """
        SELECT nt.org_id FROM node_template_module_pins ntmp
        JOIN node_templates nt ON nt.node_template_id = ntmp.node_template_id
        WHERE ntmp.node_template_module_pin_id = %s;
        """,
        (pin_id,),
    )
    row = cur.fetchone()
    if not row or row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Module pin assignment not found")
    cur.execute(
        "SELECT node_template_module_gpio_pin_id, pin_role, gpio_pin FROM node_template_module_gpio_pins WHERE node_template_module_pin_id = %s;",
        (pin_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"gpio_assignments": [{"node_template_module_gpio_pin_id": r[0], "pin_role": r[1], "gpio_pin": r[2]} for r in rows]}

@app.delete("/node_templates/module_pins/{pin_id}/gpio_pins/{gpio_assignment_id}")
def delete_gpio_assignment(pin_id: int, gpio_assignment_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        """
        SELECT nt.org_id FROM node_template_module_pins ntmp
        JOIN node_templates nt ON nt.node_template_id = ntmp.node_template_id
        WHERE ntmp.node_template_module_pin_id = %s;
        """,
        (pin_id,),
    )
    row = cur.fetchone()
    if not row or row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Module pin assignment not found")
    require_org_admin(cur, current_user)
    cur.execute(
        "DELETE FROM node_template_module_gpio_pins WHERE node_template_module_gpio_pin_id = %s AND node_template_module_pin_id = %s;",
        (gpio_assignment_id, pin_id),
    )
    log_event(cur, current_user.org_id, "node_template_gpio_removed", current_user.user_id, "node_template_module_gpio_pin",
              str(gpio_assignment_id), {"pin_id": pin_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "gpio_assignment_deleted", "node_template_module_gpio_pin_id": gpio_assignment_id}


# =====================================================================================
# Alert Templates + Rules CRUD (supports both numeric and boolean/motion-style metrics)
# =====================================================================================

class AlertTemplateCreate(BaseModel):
    name: str

class AlertTemplateRuleCreate(BaseModel):
    metric_name: str
    threshold_min: float | None = None
    threshold_max: float | None = None
    trigger_value: bool | None = None  # for boolean metrics like motion

def validate_alert_rule_shape(threshold_min, threshold_max, trigger_value):
    has_threshold = threshold_min is not None or threshold_max is not None
    has_trigger = trigger_value is not None
    if has_threshold and has_trigger:
        raise HTTPException(status_code=400, detail="Provide either threshold_min/max OR trigger_value, not both")
    if not has_threshold and not has_trigger:
        raise HTTPException(status_code=400, detail="Must provide threshold_min/threshold_max (numeric) or trigger_value (boolean)")

@app.post("/alert_templates")
def create_alert_template(data: AlertTemplateCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute(
        "INSERT INTO alert_templates (org_id, name, created_by) VALUES (%s, %s, %s) RETURNING alert_template_id;",
        (current_user.org_id, data.name, current_user.user_id),
    )
    alert_template_id = cur.fetchone()[0]
    log_event(cur, current_user.org_id, "alert_template_created", current_user.user_id, "alert_template",
              str(alert_template_id), {"name": data.name})
    conn.commit(); cur.close(); conn.close()
    return {"status": "alert_template_created", "alert_template_id": alert_template_id}

@app.get("/alert_templates")
def list_alert_templates(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT alert_template_id, name FROM alert_templates WHERE org_id = %s ORDER BY name;", (current_user.org_id,))
    templates = cur.fetchall()
    result = []
    for tid, name in templates:
        cur.execute(
            "SELECT alert_template_rule_id, metric_name, threshold_min, threshold_max, trigger_value FROM alert_template_rules WHERE alert_template_id = %s;",
            (tid,),
        )
        rules = [
            {"alert_template_rule_id": r[0], "metric_name": r[1], "threshold_min": r[2], "threshold_max": r[3], "trigger_value": r[4]}
            for r in cur.fetchall()
        ]
        result.append({"alert_template_id": tid, "name": name, "rules": rules})
    cur.close(); conn.close()
    return {"alert_templates": result}

@app.delete("/alert_templates/{alert_template_id}")
def delete_alert_template(alert_template_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute("DELETE FROM alert_templates WHERE alert_template_id = %s AND org_id = %s;", (alert_template_id, current_user.org_id))
    log_event(cur, current_user.org_id, "alert_template_deleted", current_user.user_id, "alert_template",
              str(alert_template_id), None)
    conn.commit(); cur.close(); conn.close()
    return {"status": "alert_template_deleted", "alert_template_id": alert_template_id}

@app.post("/alert_templates/{alert_template_id}/rules")
def add_alert_template_rule(alert_template_id: int, data: AlertTemplateRuleCreate, current_user: User = Depends(get_current_user)):
    validate_alert_rule_shape(data.threshold_min, data.threshold_max, data.trigger_value)
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute("SELECT 1 FROM alert_templates WHERE alert_template_id = %s AND org_id = %s;", (alert_template_id, current_user.org_id))
    if not cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Alert template not found")
    cur.execute(
        """
        INSERT INTO alert_template_rules (alert_template_id, metric_name, threshold_min, threshold_max, trigger_value)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (alert_template_id, metric_name) DO UPDATE
        SET threshold_min = EXCLUDED.threshold_min, threshold_max = EXCLUDED.threshold_max, trigger_value = EXCLUDED.trigger_value
        RETURNING alert_template_rule_id;
        """,
        (alert_template_id, data.metric_name, data.threshold_min, data.threshold_max, data.trigger_value),
    )
    rule_id = cur.fetchone()[0]
    log_event(cur, current_user.org_id, "alert_template_rule_added", current_user.user_id, "alert_template_rule",
              str(rule_id), {"alert_template_id": alert_template_id, "metric_name": data.metric_name})
    conn.commit(); cur.close(); conn.close()
    return {"status": "rule_saved", "alert_template_rule_id": rule_id}

@app.delete("/alert_templates/{alert_template_id}/rules/{rule_id}")
def delete_alert_template_rule(alert_template_id: int, rule_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    cur.execute("DELETE FROM alert_template_rules WHERE alert_template_rule_id = %s AND alert_template_id = %s;", (rule_id, alert_template_id))
    log_event(cur, current_user.org_id, "alert_template_rule_removed", current_user.user_id, "alert_template_rule",
              str(rule_id), {"alert_template_id": alert_template_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "rule_deleted", "alert_template_rule_id": rule_id}


# =====================================================================================
# Alert Rules CRUD (per-device, direct editing — the thing you asked for explicitly)
# =====================================================================================

class AlertRuleCreate(BaseModel):
    serial_number: str
    metric_name: str
    threshold_min: float | None = None
    threshold_max: float | None = None
    trigger_value: bool | None = None

def get_device_org_and_site(cur, serial_number: str):
    """Returns (org_id, site_id) for whichever of gateways/sensors owns this serial, or None."""
    cur.execute("SELECT org_id, site_id FROM gateways WHERE serial_number = %s;", (serial_number,))
    row = cur.fetchone()
    if row:
        return row
    cur.execute("SELECT org_id, site_id FROM sensors WHERE serial_number = %s;", (serial_number,))
    return cur.fetchone()

def require_device_admin(cur, current_user: User, org_id: int, site_id: int | None):
    if org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Device belongs to another organisation")
    if site_id is not None:
        require_site_access(cur, current_user, current_user.org_id, site_id, admin=True)
    else:
        require_org_access(cur, current_user, admin=True)

@app.post("/alert_rules")
def create_alert_rule(data: AlertRuleCreate, current_user: User = Depends(get_current_user)):
    validate_alert_rule_shape(data.threshold_min, data.threshold_max, data.trigger_value)
    conn = get_db(); cur = conn.cursor()
    device = get_device_org_and_site(cur, data.serial_number)
    if not device:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found")
    require_device_admin(cur, current_user, device[0], device[1])
    cur.execute(
        """
        INSERT INTO alert_rules (serial_number, metric_name, threshold_min, threshold_max, trigger_value, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (serial_number, metric_name) WHERE is_active = TRUE DO UPDATE
        SET threshold_min = EXCLUDED.threshold_min, threshold_max = EXCLUDED.threshold_max, trigger_value = EXCLUDED.trigger_value
        RETURNING alert_rule_id;
        """,
        (data.serial_number, data.metric_name, data.threshold_min, data.threshold_max, data.trigger_value, current_user.user_id),
    )
    rule_id = cur.fetchone()[0]
    log_event(cur, device[0], "alert_rule_created", current_user.user_id, "alert_rule", str(rule_id),
              {"serial_number": data.serial_number, "metric_name": data.metric_name})
    conn.commit(); cur.close(); conn.close()
    return {"status": "alert_rule_saved", "alert_rule_id": rule_id}

@app.get("/alert_rules")
def list_alert_rules(serial_number: str, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    device = get_device_org_and_site(cur, serial_number)
    if not device or device[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found")
    cur.execute(
        "SELECT alert_rule_id, metric_name, threshold_min, threshold_max, trigger_value, is_active FROM alert_rules WHERE serial_number = %s;",
        (serial_number,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"alert_rules": [
        {"alert_rule_id": r[0], "metric_name": r[1], "threshold_min": r[2], "threshold_max": r[3], "trigger_value": r[4], "is_active": r[5]}
        for r in rows
    ]}

@app.delete("/alert_rules/{alert_rule_id}")
def delete_alert_rule(alert_rule_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT serial_number FROM alert_rules WHERE alert_rule_id = %s;", (alert_rule_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Alert rule not found")
    device = get_device_org_and_site(cur, row[0])
    if not device:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found")
    require_device_admin(cur, current_user, device[0], device[1])
    cur.execute("UPDATE alert_rules SET is_active = FALSE WHERE alert_rule_id = %s;", (alert_rule_id,))
    log_event(cur, device[0], "alert_rule_deleted", current_user.user_id, "alert_rule", str(alert_rule_id),
              {"serial_number": row[0]})
    conn.commit(); cur.close(); conn.close()
    return {"status": "alert_rule_deleted", "alert_rule_id": alert_rule_id}

@app.get("/alerts")
def list_alerts(serial_number: str | None = None, status: str | None = None, current_user: User = Depends(get_current_user)):
    """Site-scoped the same way as /gateways and /sensors — alerts itself carries no
    org_id/site_id, so we resolve it by joining to whichever of gateways/sensors owns the
    serial_number."""
    conn = get_db(); cur = conn.cursor()
    site_ids = _accessible_site_ids_or_none(cur, current_user, None)
    query = """
        SELECT a.alert_id, a.alert_rule_id, a.serial_number, a.metric_name, a.triggered_value,
               a.status, a.triggered_at, a.acknowledged_by, a.acknowledged_at, a.resolved_at
        FROM alerts a
        JOIN (
            SELECT serial_number, org_id, site_id FROM gateways
            UNION ALL
            SELECT serial_number, org_id, site_id FROM sensors
        ) d ON d.serial_number = a.serial_number
        WHERE d.org_id = %s
    """
    params = [current_user.org_id]
    if site_ids is not None:
        if not site_ids:
            cur.close(); conn.close()
            return {"alerts": []}
        query += " AND d.site_id = ANY(%s)"
        params.append(site_ids)
    if serial_number is not None:
        query += " AND a.serial_number = %s"
        params.append(serial_number)
    if status is not None:
        query += " AND a.status = %s"
        params.append(status)
    query += " ORDER BY a.triggered_at DESC;"
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"alerts": [
        {"alert_id": r[0], "alert_rule_id": r[1], "serial_number": r[2], "metric_name": r[3],
         "triggered_value": r[4], "status": r[5], "triggered_at": r[6],
         "acknowledged_by": r[7], "acknowledged_at": r[8], "resolved_at": r[9]}
        for r in rows
    ]}

# =====================================================================================
# Battery profile catalog (battery_profiles, battery_discharge_points) — FE-8
# =====================================================================================
# Same shape as the MCU catalog just below: global/factory reference data, no org_id,
# platform-admin gated to create, open reads (needed to populate Node Template and
# per-device battery selectors). battery_profile_id is nullable on node_templates/
# gateways/sensors — NULL means "not powered by batteries" or "not set yet", not an error.

class BatteryProfileCreate(BaseModel):
    name: str
    chemistry: str  # 'li-ion' | 'lipo' | 'nimh' | 'alkaline' | 'cr2032'
    is_rechargeable: bool = True
    cell_count: int = 1
    nominal_voltage_mv: int
    min_voltage_mv: int
    max_voltage_mv: int
    notes: str | None = None

VALID_BATTERY_CHEMISTRIES = ("li-ion", "lipo", "nimh", "alkaline", "cr2032")

@app.post("/battery_profiles")
def create_battery_profile(data: BatteryProfileCreate, current_user: User = Depends(get_current_user)):
    if data.chemistry not in VALID_BATTERY_CHEMISTRIES:
        raise HTTPException(status_code=400, detail=f"chemistry must be one of {VALID_BATTERY_CHEMISTRIES}")
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        """
        INSERT INTO battery_profiles (name, chemistry, is_rechargeable, cell_count, nominal_voltage_mv, min_voltage_mv, max_voltage_mv, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING battery_profile_id;
        """,
        (data.name, data.chemistry, data.is_rechargeable, data.cell_count,
         data.nominal_voltage_mv, data.min_voltage_mv, data.max_voltage_mv, data.notes),
    )
    battery_profile_id = cur.fetchone()[0]
    log_platform_event(cur, "battery_profile_catalog_created", current_user.user_id, "battery_profile",
                        str(battery_profile_id), {"name": data.name, "chemistry": data.chemistry})
    conn.commit(); cur.close(); conn.close()
    return {"status": "battery_profile_created", "battery_profile_id": battery_profile_id}

@app.get("/battery_profiles")
def list_battery_profiles(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        """
        SELECT battery_profile_id, name, chemistry, is_rechargeable, cell_count,
               nominal_voltage_mv, min_voltage_mv, max_voltage_mv, notes
        FROM battery_profiles ORDER BY name;
        """
    )
    profiles = cur.fetchall()
    result = []
    for pid, name, chemistry, is_rechargeable, cell_count, nominal_mv, min_mv, max_mv, notes in profiles:
        cur.execute(
            "SELECT voltage_mv, percentage FROM battery_discharge_points WHERE battery_profile_id = %s ORDER BY voltage_mv DESC;",
            (pid,),
        )
        points = [{"voltage_mv": r[0], "percentage": r[1]} for r in cur.fetchall()]
        result.append({
            "battery_profile_id": pid, "name": name, "chemistry": chemistry,
            "is_rechargeable": is_rechargeable, "cell_count": cell_count,
            "nominal_voltage_mv": nominal_mv, "min_voltage_mv": min_mv, "max_voltage_mv": max_mv,
            "notes": notes, "discharge_points": points,
        })
    cur.close(); conn.close()
    return {"battery_profiles": result}

class BatteryDischargePointCreate(BaseModel):
    voltage_mv: int
    percentage: int

@app.post("/battery_profiles/{battery_profile_id}/discharge_points")
def add_battery_discharge_point(battery_profile_id: int, data: BatteryDischargePointCreate, current_user: User = Depends(get_current_user)):
    if not (0 <= data.percentage <= 100):
        raise HTTPException(status_code=400, detail="percentage must be between 0 and 100")
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute("SELECT 1 FROM battery_profiles WHERE battery_profile_id = %s;", (battery_profile_id,))
    if not cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Battery profile not found")
    cur.execute(
        """
        INSERT INTO battery_discharge_points (battery_profile_id, voltage_mv, percentage)
        VALUES (%s, %s, %s)
        ON CONFLICT (battery_profile_id, voltage_mv) DO UPDATE SET percentage = EXCLUDED.percentage
        RETURNING battery_discharge_point_id;
        """,
        (battery_profile_id, data.voltage_mv, data.percentage),
    )
    point_id = cur.fetchone()[0]
    log_platform_event(cur, "battery_profile_discharge_point_added", current_user.user_id, "battery_discharge_point",
                        str(point_id), {"battery_profile_id": battery_profile_id, "voltage_mv": data.voltage_mv,
                                        "percentage": data.percentage})
    conn.commit(); cur.close(); conn.close()
    return {"status": "discharge_point_saved", "battery_discharge_point_id": point_id}

class DeviceBatteryProfileUpdate(BaseModel):
    battery_profile_id: int | None = None  # null = not powered by batteries / not set

@app.post("/gateways/{gateway_id}/battery_profile")
def set_gateway_battery_profile(gateway_id: str, data: DeviceBatteryProfileUpdate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id, site_id FROM gateways WHERE gateway_id = %s;", (gateway_id,))
    row = cur.fetchone()
    if not row or row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Gateway not found")
    require_site_access(cur, current_user, current_user.org_id, row[1], admin=True)
    if data.battery_profile_id is not None:
        cur.execute("SELECT 1 FROM battery_profiles WHERE battery_profile_id = %s;", (data.battery_profile_id,))
        if not cur.fetchone():
            cur.close(); conn.close()
            raise HTTPException(status_code=404, detail="Battery profile not found")
    cur.execute("UPDATE gateways SET battery_profile_id = %s WHERE gateway_id = %s;", (data.battery_profile_id, gateway_id))
    log_event(cur, current_user.org_id, "device_battery_profile_set", current_user.user_id, "gateway", gateway_id,
              {"battery_profile_id": data.battery_profile_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "battery_profile_updated", "gateway_id": gateway_id, "battery_profile_id": data.battery_profile_id}

@app.post("/sensors/{sensor_id}/battery_profile")
def set_sensor_battery_profile(sensor_id: str, data: DeviceBatteryProfileUpdate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT org_id, site_id FROM sensors WHERE sensor_id = %s;", (sensor_id,))
    row = cur.fetchone()
    if not row or row[0] != current_user.org_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Sensor not found")
    require_site_access(cur, current_user, current_user.org_id, row[1], admin=True)
    if data.battery_profile_id is not None:
        cur.execute("SELECT 1 FROM battery_profiles WHERE battery_profile_id = %s;", (data.battery_profile_id,))
        if not cur.fetchone():
            cur.close(); conn.close()
            raise HTTPException(status_code=404, detail="Battery profile not found")
    cur.execute("UPDATE sensors SET battery_profile_id = %s WHERE sensor_id = %s;", (data.battery_profile_id, sensor_id))
    log_event(cur, current_user.org_id, "device_battery_profile_set", current_user.user_id, "sensor", sensor_id,
              {"battery_profile_id": data.battery_profile_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "battery_profile_updated", "sensor_id": sensor_id, "battery_profile_id": data.battery_profile_id}


# =====================================================================================
# Reports (RPT-5/RPT-6, DB-3) — report_templates (seeded, read-only) + user_reports
# =====================================================================================
# report_templates is metadata only (key/name/description/category) — the actual report
# *computation* lives in the frontend (frontend/reports.py), fed by data endpoints that
# already exist (readings, alerts, gateways, sensors, sites). Keeping it this way avoids
# building a generic query-builder abstraction for 9 fairly different report shapes.
# user_reports is how a customised view (site/device/date-range/thresholds, in `config`)
# gets saved under a name, without altering the template. Scoped to the owning user.

@app.get("/report_templates")
def list_report_templates(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT report_template_id, key, name, description, category FROM report_templates ORDER BY category, name;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"report_templates": [
        {"report_template_id": r[0], "key": r[1], "name": r[2], "description": r[3], "category": r[4]}
        for r in rows
    ]}

class UserReportCreate(BaseModel):
    report_template_id: int
    name: str
    config: dict = {}

@app.post("/user_reports")
def create_user_report(data: UserReportCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM report_templates WHERE report_template_id = %s;", (data.report_template_id,))
    if not cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Report template not found")
    cur.execute(
        """
        INSERT INTO user_reports (org_id, owner_user_id, report_template_id, name, config)
        VALUES (%s, %s, %s, %s, %s) RETURNING user_report_id;
        """,
        (current_user.org_id, current_user.user_id, data.report_template_id, data.name, Json(data.config)),
    )
    user_report_id = cur.fetchone()[0]
    log_event(cur, current_user.org_id, "report_created", current_user.user_id, "user_report",
              str(user_report_id), {"name": data.name, "report_template_id": data.report_template_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "user_report_created", "user_report_id": user_report_id}

@app.get("/user_reports")
def list_user_reports(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        """
        SELECT ur.user_report_id, ur.name, ur.config, ur.report_template_id, rt.key, rt.name, ur.updated_at
        FROM user_reports ur JOIN report_templates rt ON rt.report_template_id = ur.report_template_id
        WHERE ur.owner_user_id = %s ORDER BY ur.updated_at DESC;
        """,
        (current_user.user_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"user_reports": [
        {"user_report_id": r[0], "name": r[1], "config": r[2], "report_template_id": r[3],
         "template_key": r[4], "template_name": r[5], "updated_at": r[6].isoformat()}
        for r in rows
    ]}

class UserReportUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None

@app.put("/user_reports/{user_report_id}")
def update_user_report(user_report_id: int, data: UserReportUpdate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT owner_user_id FROM user_reports WHERE user_report_id = %s;", (user_report_id,))
    row = cur.fetchone()
    if not row or row[0] != current_user.user_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Report not found")
    fields, values = [], []
    if data.name is not None:
        fields.append("name = %s"); values.append(data.name)
    if data.config is not None:
        fields.append("config = %s"); values.append(Json(data.config))
    if fields:
        fields.append("updated_at = NOW()")
        values.append(user_report_id)
        cur.execute(f"UPDATE user_reports SET {', '.join(fields)} WHERE user_report_id = %s;", values)
        log_event(cur, current_user.org_id, "report_updated", current_user.user_id, "user_report",
                  str(user_report_id), {"name": data.name} if data.name is not None else None)
        conn.commit()
    cur.close(); conn.close()
    return {"status": "user_report_updated", "user_report_id": user_report_id}

@app.delete("/user_reports/{user_report_id}")
def delete_user_report(user_report_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT owner_user_id FROM user_reports WHERE user_report_id = %s;", (user_report_id,))
    row = cur.fetchone()
    if not row or row[0] != current_user.user_id:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Report not found")
    cur.execute("DELETE FROM user_reports WHERE user_report_id = %s;", (user_report_id,))
    log_event(cur, current_user.org_id, "report_deleted", current_user.user_id, "user_report",
              str(user_report_id), None)
    conn.commit(); cur.close(); conn.close()
    return {"status": "user_report_deleted", "user_report_id": user_report_id}


# =====================================================================================
# MCU catalog CRUD (mcu_variants, mcu_variant_gpio_pins, module_mcu_compatibility)
# =====================================================================================
# These three tables are GLOBAL/factory reference data (no org_id column at all — they
# describe hardware, not any one org's deployment), so mutations require the dedicated
# users.is_watchdog_admin flag (require_platform_admin), not an ordinary org's Global
# Admin. Reads stay open to any authenticated user (needed to populate node-template
# dropdowns etc).

class McuVariantCreate(BaseModel):
    name: str

@app.post("/mcu_variants")
def create_mcu_variant(data: McuVariantCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute("INSERT INTO mcu_variants (name) VALUES (%s) RETURNING mcu_variant_id;", (data.name,))
    mcu_variant_id = cur.fetchone()[0]
    log_platform_event(cur, "mcu_variant_catalog_created", current_user.user_id, "mcu_variant",
                        str(mcu_variant_id), {"name": data.name})
    conn.commit(); cur.close(); conn.close()
    return {"status": "mcu_variant_created", "mcu_variant_id": mcu_variant_id}

@app.get("/mcu_variants")
def list_mcu_variants(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT mcu_variant_id, name FROM mcu_variants ORDER BY name;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"mcu_variants": [{"mcu_variant_id": r[0], "name": r[1]} for r in rows]}

class GpioPinCreate(BaseModel):
    gpio_pin: str
    status: str = "available"  # 'available' | 'reserved' | 'restricted'
    notes: str | None = None

@app.post("/mcu_variants/{mcu_variant_id}/gpio_pins")
def add_gpio_pin(mcu_variant_id: int, data: GpioPinCreate, current_user: User = Depends(get_current_user)):
    if data.status not in ("available", "reserved", "restricted"):
        raise HTTPException(status_code=400, detail="status must be 'available', 'reserved', or 'restricted'")
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        """
        INSERT INTO mcu_variant_gpio_pins (mcu_variant_id, gpio_pin, status, notes)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (mcu_variant_id, gpio_pin) DO UPDATE SET status = EXCLUDED.status, notes = EXCLUDED.notes
        RETURNING mcu_variant_gpio_pin_id;
        """,
        (mcu_variant_id, data.gpio_pin, data.status, data.notes),
    )
    pin_id = cur.fetchone()[0]
    log_platform_event(cur, "mcu_variant_gpio_pin_added", current_user.user_id, "mcu_variant_gpio_pin",
                        str(pin_id), {"mcu_variant_id": mcu_variant_id, "gpio_pin": data.gpio_pin, "status": data.status})
    conn.commit(); cur.close(); conn.close()
    return {"status": "gpio_pin_saved", "mcu_variant_gpio_pin_id": pin_id}

@app.get("/mcu_variants/{mcu_variant_id}/gpio_pins")
def list_gpio_pins(mcu_variant_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT mcu_variant_gpio_pin_id, gpio_pin, status, notes FROM mcu_variant_gpio_pins WHERE mcu_variant_id = %s;",
        (mcu_variant_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"gpio_pins": [{"mcu_variant_gpio_pin_id": r[0], "gpio_pin": r[1], "status": r[2], "notes": r[3]} for r in rows]}

class ModuleCompatibilityCreate(BaseModel):
    module_type_id: int
    mcu_variant_id: int

@app.post("/module_mcu_compatibility")
def add_module_compatibility(data: ModuleCompatibilityCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        "INSERT INTO module_mcu_compatibility (module_type_id, mcu_variant_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
        (data.module_type_id, data.mcu_variant_id),
    )
    log_platform_event(cur, "module_mcu_compatibility_created", current_user.user_id, "module_mcu_compatibility",
                        f"{data.module_type_id}:{data.mcu_variant_id}",
                        {"module_type_id": data.module_type_id, "mcu_variant_id": data.mcu_variant_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "compatibility_added"}

@app.get("/module_mcu_compatibility")
def list_module_compatibility(mcu_variant_id: int | None = None, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    if mcu_variant_id is not None:
        cur.execute("SELECT module_type_id, mcu_variant_id FROM module_mcu_compatibility WHERE mcu_variant_id = %s;", (mcu_variant_id,))
    else:
        cur.execute("SELECT module_type_id, mcu_variant_id FROM module_mcu_compatibility;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"compatibility": [{"module_type_id": r[0], "mcu_variant_id": r[1]} for r in rows]}

@app.delete("/module_mcu_compatibility")
def delete_module_compatibility(module_type_id: int, mcu_variant_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        "DELETE FROM module_mcu_compatibility WHERE module_type_id = %s AND mcu_variant_id = %s;",
        (module_type_id, mcu_variant_id),
    )
    log_platform_event(cur, "module_mcu_compatibility_deleted", current_user.user_id, "module_mcu_compatibility",
                        f"{module_type_id}:{mcu_variant_id}",
                        {"module_type_id": module_type_id, "mcu_variant_id": mcu_variant_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "compatibility_removed"}


# =====================================================================================
# WatchDog Employee Portal — device_registry CRUD
# =====================================================================================
# Previously "no endpoint exists at all, by original design (factory data, no org admin
# should fabricate it)". Now built, gated by require_platform_admin (is_watchdog_admin
# flag) rather than any org-level role, matching that original design intent — this is
# WatchDog-staff-only, not exposed to any customer org regardless of their role there.

class DeviceRegistryCreate(BaseModel):
    serial_number: str
    device_type: str  # 'gateway' or 'sensor'
    model: str | None = None
    mcu_variant_id: int | None = None
    flash_kb: int | None = None
    psram_kb: int | None = None
    ram_kb: int | None = None

@app.post("/device_registry")
def create_device_registry_entry(data: DeviceRegistryCreate, current_user: User = Depends(get_current_user)):
    if data.device_type not in ("gateway", "sensor"):
        raise HTTPException(status_code=400, detail="device_type must be 'gateway' or 'sensor'")
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        """
        INSERT INTO device_registry (serial_number, device_type, model, mcu_variant_id, flash_kb, psram_kb, ram_kb)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
        """,
        (data.serial_number, data.device_type, data.model, data.mcu_variant_id,
         data.flash_kb, data.psram_kb, data.ram_kb),
    )
    log_platform_event(cur, "device_registry_entry_created", current_user.user_id, "device_registry",
                        data.serial_number, {"device_type": data.device_type, "model": data.model})
    conn.commit(); cur.close(); conn.close()
    return {"status": "device_registered", "serial_number": data.serial_number}

@app.get("/device_registry")
def list_device_registry(is_provisioned: bool | None = None, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    if is_provisioned is not None:
        cur.execute(
            "SELECT serial_number, device_type, model, mcu_variant_id, is_provisioned, provisioned_at FROM device_registry WHERE is_provisioned = %s ORDER BY serial_number;",
            (is_provisioned,),
        )
    else:
        cur.execute(
            "SELECT serial_number, device_type, model, mcu_variant_id, is_provisioned, provisioned_at FROM device_registry ORDER BY serial_number;"
        )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"devices": [
        {"serial_number": r[0], "device_type": r[1], "model": r[2], "mcu_variant_id": r[3],
         "is_provisioned": r[4], "provisioned_at": r[5].isoformat() if r[5] else None}
        for r in rows
    ]}

@app.get("/device_registry/{serial_number}")
def get_device_registry_entry(serial_number: str, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        "SELECT serial_number, device_type, model, mcu_variant_id, flash_kb, psram_kb, ram_kb, is_provisioned, provisioned_at FROM device_registry WHERE serial_number = %s;",
        (serial_number,),
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Device not found in registry")
    return {
        "serial_number": row[0], "device_type": row[1], "model": row[2], "mcu_variant_id": row[3],
        "flash_kb": row[4], "psram_kb": row[5], "ram_kb": row[6],
        "is_provisioned": row[7], "provisioned_at": row[8].isoformat() if row[8] else None,
    }

class DeviceRegistryUpdate(BaseModel):
    model: str | None = None
    mcu_variant_id: int | None = None
    flash_kb: int | None = None
    psram_kb: int | None = None
    ram_kb: int | None = None

@app.patch("/device_registry/{serial_number}")
def update_device_registry_entry(serial_number: str, data: DeviceRegistryUpdate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute("SELECT is_provisioned FROM device_registry WHERE serial_number = %s;", (serial_number,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found in registry")
    if row[0]:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Cannot edit factory specs after a device has been provisioned")
    fields, values = [], []
    for col in ("model", "mcu_variant_id", "flash_kb", "psram_kb", "ram_kb"):
        v = getattr(data, col)
        if v is not None:
            fields.append(f"{col} = %s")
            values.append(v)
    if fields:
        values.append(serial_number)
        cur.execute(f"UPDATE device_registry SET {', '.join(fields)} WHERE serial_number = %s;", values)
        updated_fields = [col for col in ("model", "mcu_variant_id", "flash_kb", "psram_kb", "ram_kb")
                           if getattr(data, col) is not None]
        log_platform_event(cur, "device_registry_entry_updated", current_user.user_id, "device_registry",
                            serial_number, {"updated_fields": updated_fields})
    conn.commit(); cur.close(); conn.close()
    return {"status": "device_updated", "serial_number": serial_number}

@app.delete("/device_registry/{serial_number}")
def delete_device_registry_entry(serial_number: str, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute("SELECT is_provisioned FROM device_registry WHERE serial_number = %s;", (serial_number,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found in registry")
    if row[0]:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Cannot delete a provisioned device from the registry — deprovision it first")
    cur.execute("DELETE FROM device_registry WHERE serial_number = %s;", (serial_number,))
    log_platform_event(cur, "device_registry_entry_deleted", current_user.user_id, "device_registry",
                        serial_number, None)
    conn.commit(); cur.close(); conn.close()
    return {"status": "device_deleted", "serial_number": serial_number}

class DeviceRadioCreate(BaseModel):
    radio_type: str
    mac_address: str | None = None

@app.post("/device_registry/{serial_number}/radios")
def add_device_radio(serial_number: str, data: DeviceRadioCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute("SELECT 1 FROM device_registry WHERE serial_number = %s;", (serial_number,))
    if not cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Device not found in registry")
    cur.execute(
        "INSERT INTO device_radios (serial_number, radio_type, mac_address) VALUES (%s, %s, %s) RETURNING device_radio_id;",
        (serial_number, data.radio_type, data.mac_address),
    )
    radio_id = cur.fetchone()[0]
    log_platform_event(cur, "device_registry_radio_added", current_user.user_id, "device_radio",
                        str(radio_id), {"serial_number": serial_number, "radio_type": data.radio_type})
    conn.commit(); cur.close(); conn.close()
    return {"status": "radio_added", "device_radio_id": radio_id}

@app.get("/device_registry/{serial_number}/radios")
def list_device_radios(serial_number: str, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        "SELECT device_radio_id, radio_type, mac_address FROM device_radios WHERE serial_number = %s;",
        (serial_number,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"radios": [{"device_radio_id": r[0], "radio_type": r[1], "mac_address": r[2]} for r in rows]}

@app.delete("/device_registry/{serial_number}/radios/{device_radio_id}")
def delete_device_radio(serial_number: str, device_radio_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute("DELETE FROM device_radios WHERE device_radio_id = %s AND serial_number = %s;", (device_radio_id, serial_number))
    log_platform_event(cur, "device_registry_radio_removed", current_user.user_id, "device_radio",
                        str(device_radio_id), {"serial_number": serial_number})
    conn.commit(); cur.close(); conn.close()
    return {"status": "radio_deleted", "device_radio_id": device_radio_id}


# =====================================================================================
# WatchDog Employee Portal — sensor_module_types CRUD
# =====================================================================================

class SensorModuleTypeCreate(BaseModel):
    module_type: str  # short/unique code, e.g. 'temp_humidity_v2'
    name: str         # display name
    communication_type: str | None = None
    default_i2c_address: str | None = None

@app.post("/sensor_module_types")
def create_sensor_module_type(data: SensorModuleTypeCreate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        """
        INSERT INTO sensor_module_types (module_type, name, communication_type, default_i2c_address)
        VALUES (%s, %s, %s, %s) RETURNING module_type_id;
        """,
        (data.module_type, data.name, data.communication_type, data.default_i2c_address),
    )
    module_type_id = cur.fetchone()[0]
    log_platform_event(cur, "sensor_module_type_created", current_user.user_id, "sensor_module_type",
                        str(module_type_id), {"module_type": data.module_type, "name": data.name})
    conn.commit(); cur.close(); conn.close()
    return {"status": "module_type_created", "module_type_id": module_type_id}

@app.get("/sensor_module_types")
def list_sensor_module_types(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT module_type_id, module_type, name, communication_type, default_i2c_address FROM sensor_module_types ORDER BY name;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"module_types": [
        {"module_type_id": r[0], "module_type": r[1], "name": r[2], "communication_type": r[3], "default_i2c_address": r[4]}
        for r in rows
    ]}

class SensorModuleTypeUpdate(BaseModel):
    name: str | None = None
    communication_type: str | None = None
    default_i2c_address: str | None = None

@app.patch("/sensor_module_types/{module_type_id}")
def update_sensor_module_type(module_type_id: int, data: SensorModuleTypeUpdate, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    fields, values = [], []
    for col in ("name", "communication_type", "default_i2c_address"):
        v = getattr(data, col)
        if v is not None:
            fields.append(f"{col} = %s")
            values.append(v)
    if not fields:
        cur.close(); conn.close()
        return {"status": "no_changes", "module_type_id": module_type_id}
    values.append(module_type_id)
    cur.execute(f"UPDATE sensor_module_types SET {', '.join(fields)} WHERE module_type_id = %s;", values)
    if cur.rowcount == 0:
        conn.rollback(); cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Module type not found")
    log_platform_event(cur, "sensor_module_type_updated", current_user.user_id, "sensor_module_type",
                        str(module_type_id), {"updated_fields": [col for col in ("name", "communication_type", "default_i2c_address")
                                                                  if getattr(data, col) is not None]})
    conn.commit(); cur.close(); conn.close()
    return {"status": "module_type_updated", "module_type_id": module_type_id}

@app.delete("/sensor_module_types/{module_type_id}")
def delete_sensor_module_type(module_type_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute("DELETE FROM sensor_module_types WHERE module_type_id = %s;", (module_type_id,))
    if cur.rowcount == 0:
        conn.rollback(); cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Module type not found")
    log_platform_event(cur, "sensor_module_type_deleted", current_user.user_id, "sensor_module_type",
                        str(module_type_id), None)
    conn.commit(); cur.close(); conn.close()
    return {"status": "module_type_deleted", "module_type_id": module_type_id}


# =====================================================================================
# Support Access — opt-in, read-only 24h impersonation for WatchDog support staff
# =====================================================================================
# Design note: is_watchdog_admin is a flat flag rather than a rank-based role
# specifically so platform access and org access stay structurally separate — see
# require_platform_admin's docstring. Read-only is enforced server-side by the
# block_support_session_mutations middleware above, not left as a frontend courtesy.

def create_support_view_token(admin_id: int, target_user_id: int, grant_id: int, session_id: int,
                               expires_minutes: int = 60) -> str:
    payload = {
        "typ": "support_view",
        "admin_id": admin_id,
        "target_user_id": target_user_id,
        "grant_id": grant_id,
        "session_id": session_id,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

@app.post("/support-access/enable")
def enable_support_access(current_user: User = Depends(get_current_user)):
    """Any user may opt themselves in — this is the user granting WatchDog support staff
    permission to view (not edit) their org's data for 24h, not an admin action."""
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT grant_id FROM support_access_grants WHERE user_id = %s AND expires_at > NOW() AND revoked_at IS NULL;",
        (current_user.user_id,),
    )
    if cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Support Access is already enabled")
    expires_at = datetime.utcnow() + timedelta(hours=24)
    cur.execute(
        "INSERT INTO support_access_grants (user_id, expires_at) VALUES (%s, %s) RETURNING grant_id;",
        (current_user.user_id, expires_at),
    )
    grant_id = cur.fetchone()[0]
    log_event(cur, current_user.org_id, "support_access_enabled", current_user.user_id, "user",
              str(current_user.user_id), {"grant_id": grant_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "enabled", "grant_id": grant_id, "expires_at": expires_at.isoformat()}

@app.post("/support-access/revoke")
def revoke_support_access(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE support_access_grants SET revoked_at = NOW() WHERE user_id = %s AND expires_at > NOW() AND revoked_at IS NULL;",
        (current_user.user_id,),
    )
    updated = cur.rowcount
    if updated > 0:
        log_event(cur, current_user.org_id, "support_access_revoked", current_user.user_id, "user",
                  str(current_user.user_id), None)
    conn.commit(); cur.close(); conn.close()
    if updated == 0:
        raise HTTPException(status_code=400, detail="No active Support Access grant to revoke")
    return {"status": "revoked"}

@app.get("/support-access/status")
def support_access_status(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        """
        SELECT grant_id, granted_at, expires_at FROM support_access_grants
        WHERE user_id = %s AND expires_at > NOW() AND revoked_at IS NULL
        ORDER BY granted_at DESC LIMIT 1;
        """,
        (current_user.user_id,),
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return {"enabled": False}
    grant_id, granted_at, expires_at = row
    return {"enabled": True, "grant_id": grant_id, "granted_at": granted_at.isoformat(), "expires_at": expires_at.isoformat()}

@app.get("/support-access/grants")
def list_support_access_grants(current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        """
        SELECT g.grant_id, g.user_id, u.email, u.org_id, g.granted_at, g.expires_at
        FROM support_access_grants g JOIN users u ON u.user_id = g.user_id
        WHERE g.expires_at > NOW() AND g.revoked_at IS NULL
        ORDER BY g.granted_at DESC;
        """
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"grants": [
        {"grant_id": r[0], "user_id": r[1], "email": r[2], "org_id": r[3],
         "granted_at": r[4].isoformat(), "expires_at": r[5].isoformat()}
        for r in rows
    ]}

@app.get("/support-access/sessions/mine")
def list_my_support_sessions(current_user: User = Depends(get_current_user)):
    """API-7: an admin's own Support Access session history — previously the only read
    path was /support-access/grants (currently-active grants org-wide), with no way to see
    what *you* personally have looked at. Most-recent first, capped at 200."""
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        """
        SELECT s.session_id, s.grant_id, s.target_user_id, u.email, s.started_at, s.ended_at
        FROM support_access_sessions s JOIN users u ON u.user_id = s.target_user_id
        WHERE s.admin_user_id = %s ORDER BY s.started_at DESC LIMIT 200;
        """,
        (current_user.user_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"sessions": [
        {"session_id": r[0], "grant_id": r[1], "target_user_id": r[2], "target_email": r[3],
         "started_at": r[4].isoformat(), "ended_at": r[5].isoformat() if r[5] else None}
        for r in rows
    ]}

class SupportSessionStart(BaseModel):
    grant_id: int

@app.post("/support-access/sessions/start")
def start_support_session(data: SupportSessionStart, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        "SELECT user_id FROM support_access_grants WHERE grant_id = %s AND expires_at > NOW() AND revoked_at IS NULL;",
        (data.grant_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Grant is not active (expired, revoked, or doesn't exist)")
    target_user_id = row[0]

    cur.execute(
        "INSERT INTO support_access_sessions (grant_id, admin_user_id, target_user_id) VALUES (%s, %s, %s) RETURNING session_id;",
        (data.grant_id, current_user.user_id, target_user_id),
    )
    session_id = cur.fetchone()[0]

    cur.execute("SELECT org_id FROM users WHERE user_id = %s;", (target_user_id,))
    target_org_id = cur.fetchone()[0]
    log_event(cur, target_org_id, "support_access_session_started", current_user.user_id,
              "user", str(target_user_id), {"session_id": session_id, "grant_id": data.grant_id})
    conn.commit(); cur.close(); conn.close()

    support_token = create_support_view_token(current_user.user_id, target_user_id, data.grant_id, session_id)
    return {"status": "session_started", "session_id": session_id, "support_token": support_token, "token_type": "bearer"}

@app.post("/support-access/sessions/{session_id}/end")
def end_support_session(session_id: int, current_user: User = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    cur.execute(
        "SELECT target_user_id FROM support_access_sessions WHERE session_id = %s AND admin_user_id = %s AND ended_at IS NULL;",
        (session_id, current_user.user_id),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Session not found, already ended, or not started by you")
    target_user_id = row[0]
    cur.execute("UPDATE support_access_sessions SET ended_at = NOW() WHERE session_id = %s;", (session_id,))
    cur.execute("SELECT org_id FROM users WHERE user_id = %s;", (target_user_id,))
    target_org_id = cur.fetchone()[0]
    log_event(cur, target_org_id, "support_access_session_ended", current_user.user_id, "user", str(target_user_id), {"session_id": session_id})
    conn.commit(); cur.close(); conn.close()
    return {"status": "session_ended", "session_id": session_id}

# =====================================================================================
# Audit Log — API-5
# =====================================================================================

@app.get("/events")
def list_events(event_type: str | None = None, target_type: str | None = None,
                 actor_user_id: int | None = None, start_date: str | None = None,
                 end_date: str | None = None, limit: int = 100, offset: int = 0,
                 current_user: User = Depends(get_current_user)):
    """Org-scoped audit log read. Same RBAC bar as /backups. Table name is built from
    current_user.org_id, a trusted int resolved from the JWT via get_current_user — never
    from request input, same trust boundary log_event() itself relies on."""
    conn = get_db(); cur = conn.cursor()
    require_org_admin(cur, current_user)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    tbl = f"org_event_log_org_{int(current_user.org_id)}"
    query = f"SELECT event_id, event_type, actor_user_id, target_type, target_id, details, created_at FROM {tbl} WHERE TRUE"
    params = []
    if event_type is not None:
        query += " AND event_type = %s"; params.append(event_type)
    if target_type is not None:
        query += " AND target_type = %s"; params.append(target_type)
    if actor_user_id is not None:
        query += " AND actor_user_id = %s"; params.append(actor_user_id)
    if start_date is not None:
        query += " AND created_at::date >= %s::date"; params.append(start_date)
    if end_date is not None:
        query += " AND created_at::date <= %s::date"; params.append(end_date)
    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s;"
    params.extend([limit, offset])
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"events": [
        {"event_id": r[0], "event_type": r[1], "actor_user_id": r[2], "target_type": r[3],
         "target_id": r[4], "details": r[5], "created_at": r[6].isoformat() if r[6] else None}
        for r in rows
    ]}

@app.get("/events/platform")
def list_platform_events(event_type: str | None = None, target_type: str | None = None,
                          actor_user_id: int | None = None, org_id: int | None = None,
                          start_date: str | None = None, end_date: str | None = None,
                          limit: int = 100, offset: int = 0,
                          current_user: User = Depends(get_current_user)):
    """Platform-wide audit log read, is_watchdog_admin only. Cross-org tenant events —
    unioned across each org's physical event-log table — plus WatchDog-staff
    platform-catalog events from platform_event_log. Per-org table names are built from
    org_id values read from `organisations` itself, never from request input, same trust
    boundary log_event() already relies on."""
    conn = get_db(); cur = conn.cursor()
    require_platform_admin(cur, current_user)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    cur.execute("SELECT org_id, name FROM organisations ORDER BY org_id;")
    orgs = cur.fetchall()
    if org_id is not None:
        orgs = [o for o in orgs if o[0] == org_id]

    org_events = []
    if orgs:
        branches = []
        union_params = []
        for oid, oname in orgs:
            tbl = f"org_event_log_org_{int(oid)}"
            branches.append(
                f"SELECT %s::int AS org_id, %s::text AS org_name, event_id, event_type, "
                f"actor_user_id, target_type, target_id, details, created_at FROM {tbl}"
            )
            union_params.extend([oid, oname])
        outer = f"SELECT * FROM ({' UNION ALL '.join(branches)}) e WHERE TRUE"
        params = list(union_params)
        if event_type is not None:
            outer += " AND event_type = %s"; params.append(event_type)
        if target_type is not None:
            outer += " AND target_type = %s"; params.append(target_type)
        if actor_user_id is not None:
            outer += " AND actor_user_id = %s"; params.append(actor_user_id)
        if start_date is not None:
            outer += " AND created_at::date >= %s::date"; params.append(start_date)
        if end_date is not None:
            outer += " AND created_at::date <= %s::date"; params.append(end_date)
        outer += " ORDER BY created_at DESC LIMIT %s OFFSET %s;"
        params.extend([limit, offset])
        cur.execute(outer, params)
        org_events = [
            {"org_id": r[0], "org_name": r[1], "event_id": r[2], "event_type": r[3],
             "actor_user_id": r[4], "target_type": r[5], "target_id": r[6], "details": r[7],
             "created_at": r[8].isoformat() if r[8] else None}
            for r in cur.fetchall()
        ]

    platform_query = ("SELECT event_id, event_type, actor_user_id, target_type, target_id, "
                       "details, created_at FROM platform_event_log WHERE TRUE")
    platform_params = []
    if event_type is not None:
        platform_query += " AND event_type = %s"; platform_params.append(event_type)
    if target_type is not None:
        platform_query += " AND target_type = %s"; platform_params.append(target_type)
    if actor_user_id is not None:
        platform_query += " AND actor_user_id = %s"; platform_params.append(actor_user_id)
    if start_date is not None:
        platform_query += " AND created_at::date >= %s::date"; platform_params.append(start_date)
    if end_date is not None:
        platform_query += " AND created_at::date <= %s::date"; platform_params.append(end_date)
    platform_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s;"
    platform_params.extend([limit, offset])
    cur.execute(platform_query, platform_params)
    platform_events = [
        {"event_id": r[0], "event_type": r[1], "actor_user_id": r[2], "target_type": r[3],
         "target_id": r[4], "details": r[5], "created_at": r[6].isoformat() if r[6] else None}
        for r in cur.fetchall()
    ]

    cur.close(); conn.close()
    return {"org_events": org_events, "platform_events": platform_events}