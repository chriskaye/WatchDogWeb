"""
Background job logic for WatchDogWeb: backups, retention, GDPR sweep.

Deliberately kept free of FastAPI/pydantic imports so it can be used both by main.py
(inside request handlers) and by scheduler.py (a separate long-running process with no
web framework loaded) without dragging in route registration.

BACKUP SCOPE (as of this pass): covers every org-scoped configuration table --
sites, gateways, sensors, node_templates, alert_templates, crypto_profiles, users,
user_auth_methods, user_site_roles, sensor_capabilities, alert_rules, alert_template_rules.

Deliberately EXCLUDED: sensor_data (time-series telemetry), alerts (operational/transient),
ota_jobs (operational), backups/org_backup_settings/gdpr_deletion_requests/org_event_log
(these describe the backup/audit system itself, not "your data"), and device_registry/
device_radios/device_installed_modules/mcu_variants/mcu_variant_gpio_pins/
module_mcu_compatibility (factory/global reference data, not org-scoped). Shout if you want
sensor_data or alerts included -- that changes the storage/retention math significantly
since those tables can be large and fast-growing, unlike everything currently in scope.

NOTE: users is now included per your request, which means password_hash ends up inside
backup_snapshot_data_org_<id> as part of the row JSON. That table isn't currently
encrypted at rest beyond whatever Postgres-level encryption you have configured -- worth
knowing since it wasn't the case before this change.
"""

import os
import json
import hashlib
from datetime import datetime
import psycopg2


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "example"),
        dbname=os.getenv("DB_NAME", "postgres"),
    )


# Tables with a direct org_id column
BACKUP_TABLES = [
    ("sites", "site_id"),
    ("gateways", "gateway_id"),
    ("sensors", "sensor_id"),
    ("node_templates", "node_template_id"),
    ("alert_templates", "alert_template_id"),
    ("crypto_profiles", "crypto_id"),
    ("users", "user_id"),
]

# Tables scoped to an org only via a join -- (table_name, pk_column, sql, params_fn)
# params_fn takes org_id and returns the tuple of query params for `sql`.
CHILD_BACKUP_TABLES = [
    (
        "user_auth_methods", "auth_id",
        "SELECT * FROM user_auth_methods WHERE user_id IN (SELECT user_id FROM users WHERE org_id = %s);",
        lambda org_id: (org_id,),
    ),
    (
        "user_site_roles", "user_site_role_id",
        "SELECT * FROM user_site_roles WHERE user_id IN (SELECT user_id FROM users WHERE org_id = %s);",
        lambda org_id: (org_id,),
    ),
    (
        "sensor_capabilities", "id",
        "SELECT * FROM sensor_capabilities WHERE sensor_id IN (SELECT sensor_id FROM sensors WHERE org_id = %s);",
        lambda org_id: (org_id,),
    ),
    (
        "alert_rules", "alert_rule_id",
        "SELECT * FROM alert_rules WHERE serial_number IN ("
        "SELECT serial_number FROM gateways WHERE org_id = %s "
        "UNION SELECT serial_number FROM sensors WHERE org_id = %s);",
        lambda org_id: (org_id, org_id),
    ),
    (
        "alert_template_rules", "alert_template_rule_id",
        "SELECT * FROM alert_template_rules WHERE alert_template_id IN "
        "(SELECT alert_template_id FROM alert_templates WHERE org_id = %s);",
        lambda org_id: (org_id,),
    ),
]

RESTORE_PK = dict(BACKUP_TABLES) | {name: pk for name, pk, _sql, _params in CHILD_BACKUP_TABLES}


def compute_row_hash(row_dict: dict) -> str:
    canonical = json.dumps(row_dict, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _store_snapshot_row(cur, data_tbl: str, link_tbl: str, backup_id: int, table_name: str, row_dict: dict):
    row_hash = compute_row_hash(row_dict)
    cur.execute(
        f"""
        INSERT INTO {data_tbl} (source_table, row_hash, row_data)
        VALUES (%s, %s, %s::jsonb)
        ON CONFLICT (source_table, row_hash) DO NOTHING
        RETURNING snapshot_data_id;
        """,
        (table_name, row_hash, json.dumps(row_dict, default=str)),
    )
    result = cur.fetchone()
    if result:
        snapshot_data_id = result[0]
    else:
        cur.execute(
            f"SELECT snapshot_data_id FROM {data_tbl} WHERE source_table = %s AND row_hash = %s;",
            (table_name, row_hash),
        )
        snapshot_data_id = cur.fetchone()[0]
    cur.execute(
        f"INSERT INTO {link_tbl} (backup_id, snapshot_data_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
        (backup_id, snapshot_data_id),
    )


def snapshot_org_data(cur, org_id: int, backup_id: int):
    data_tbl = f"backup_snapshot_data_org_{org_id}"
    link_tbl = f"backup_snapshot_links_org_{org_id}"

    for table_name, _pk in BACKUP_TABLES:
        cur.execute(f"SELECT * FROM {table_name} WHERE org_id = %s;", (org_id,))
        colnames = [d[0] for d in cur.description]
        for row in cur.fetchall():
            _store_snapshot_row(cur, data_tbl, link_tbl, backup_id, table_name, dict(zip(colnames, row)))

    for table_name, _pk, sql, params_fn in CHILD_BACKUP_TABLES:
        cur.execute(sql, params_fn(org_id))
        colnames = [d[0] for d in cur.description]
        for row in cur.fetchall():
            _store_snapshot_row(cur, data_tbl, link_tbl, backup_id, table_name, dict(zip(colnames, row)))


def prune_org_backups(cur, org_id: int):
    cur.execute(
        "SELECT daily_retention_count, weekly_retention_count, monthly_retention_count FROM org_backup_settings WHERE org_id = %s;",
        (org_id,),
    )
    row = cur.fetchone()
    if not row:
        return
    daily_n, weekly_n, monthly_n = row
    # annual has no retention cap (keep forever) -- intentionally excluded from this list
    for schedule_type, keep_n in (("daily", daily_n), ("weekly", weekly_n), ("monthly", monthly_n)):
        cur.execute(
            """
            SELECT backup_id FROM backups
            WHERE org_id = %s AND schedule_type = %s AND status = 'completed'
            ORDER BY created_at DESC OFFSET %s;
            """,
            (org_id, schedule_type, keep_n),
        )
        for (backup_id,) in cur.fetchall():
            cur.execute("DELETE FROM backups WHERE backup_id = %s;", (backup_id,))


def cleanup_orphaned_snapshots(cur, org_id: int):
    data_tbl = f"backup_snapshot_data_org_{org_id}"
    link_tbl = f"backup_snapshot_links_org_{org_id}"
    cur.execute(
        f"""
        DELETE FROM {data_tbl} d
        WHERE NOT EXISTS (SELECT 1 FROM {link_tbl} l WHERE l.snapshot_data_id = d.snapshot_data_id);
        """
    )


def run_scheduled_backup(cur, org_id: int, schedule_type: str) -> int:
    cur.execute(
        """
        INSERT INTO backups (org_id, name, schedule_type, status, started_at)
        VALUES (%s, %s, %s, 'in_progress', NOW())
        RETURNING backup_id;
        """,
        (org_id, f"{schedule_type}-{datetime.utcnow().date()}", schedule_type),
    )
    backup_id = cur.fetchone()[0]
    snapshot_org_data(cur, org_id, backup_id)
    cur.execute("UPDATE backups SET status = 'completed', completed_at = NOW() WHERE backup_id = %s;", (backup_id,))
    return backup_id


def run_weekly_fallback_backup(cur, org_id: int):
    """Orgs with backups disabled still get exactly one, continually-overwritten weekly slot."""
    cur.execute("SELECT backup_id FROM backups WHERE org_id = %s AND schedule_type = 'weekly';", (org_id,))
    row = cur.fetchone()
    if row:
        cur.execute("DELETE FROM backups WHERE backup_id = %s;", (row[0],))
    run_scheduled_backup(cur, org_id, "weekly")


def run_gdpr_deletion_sweep(cur):
    cur.execute(
        "SELECT gdpr_deletion_request_id, org_id FROM gdpr_deletion_requests WHERE status = 'pending' AND scheduled_for <= NOW();"
    )
    for req_id, org_id in cur.fetchall():
        cur.execute("SELECT hard_delete_organisation(%s);", (org_id,))
        cur.execute(
            "UPDATE gdpr_deletion_requests SET status = 'completed', completed_at = NOW() WHERE gdpr_deletion_request_id = %s;",
            (req_id,),
        )


def sweep_stale_support_sessions(cur) -> int:
    """API-7: a support_access_session with no /end call just sits ended_at IS NULL
    forever once its underlying grant expires or is revoked -- harmless functionally
    since get_current_user() already revalidates grant liveness per-request against the
    support_view JWT, but the table doesn't self-clean without this. Closes any open
    session whose grant is no longer live. Returns the count closed, for logging."""
    cur.execute(
        """
        UPDATE support_access_sessions s SET ended_at = NOW()
        FROM support_access_grants g
        WHERE s.grant_id = g.grant_id AND s.ended_at IS NULL
          AND (g.expires_at <= NOW() OR g.revoked_at IS NOT NULL);
        """
    )
    return cur.rowcount


def get_all_org_ids(cur) -> list[int]:
    cur.execute("SELECT org_id FROM organisations;")
    return [r[0] for r in cur.fetchall()]


def get_backup_enabled_org_ids(cur) -> list[int]:
    cur.execute("SELECT org_id FROM org_backup_settings WHERE is_enabled = TRUE;")
    return [r[0] for r in cur.fetchall()]


def get_backup_disabled_org_ids(cur) -> list[int]:
    """Orgs with no org_backup_settings row are treated as disabled (column defaults to FALSE)."""
    cur.execute(
        """
        SELECT o.org_id FROM organisations o
        LEFT JOIN org_backup_settings s ON s.org_id = o.org_id
        WHERE s.is_enabled IS NOT TRUE;
        """
    )
    return [r[0] for r in cur.fetchall()]