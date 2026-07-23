"""
Standalone scheduler process for WatchDogWeb backup/retention/GDPR jobs.

Runs as its own container (see docker-compose.yml "scheduler" service), built from the
same image as the api service but running this script instead of uvicorn. Talks to
Postgres directly via jobs.py -- it does not go through the FastAPI app at all, so it
stays lightweight and has no HTTP surface of its own.

Schedule (all times UTC, chosen to run overnight/off-peak; adjust freely):
  - daily backups         : 02:00 every day, for orgs with backups enabled
  - weekly backups        : 03:00 every Sunday, for orgs with backups enabled
  - monthly backups       : 04:00 on the 1st of the month, for orgs with backups enabled
  - annual backups        : 05:00 on Jan 1st, for orgs with backups enabled
  - weekly fallback backup: 03:30 every Sunday, for orgs with backups DISABLED
  - retention pruning + orphan cleanup : 06:00 every day, all orgs
  - GDPR deletion sweep   : every hour, on the hour (deletions are time-sensitive to the
    14-day window, so this runs far more often than the backup jobs)
  - Support Access session sweep : every hour, at :15 (closes stale open sessions whose
    grant has since expired/been revoked -- see jobs.sweep_stale_support_sessions)

API-6 (scheduler robustness): each job now gets one retry with a short backoff before
being logged as failed, rather than failing silently on the first transient error (a
dropped DB connection, a momentary lock). Still no alerting beyond stdout -- piping a
failure notification to platform admins via the email backend is a real follow-up, not
done here; flagged rather than half-built.
"""

import time
from apscheduler.schedulers.blocking import BlockingScheduler
import jobs

RETRY_DELAY_SECONDS = 5


def _run(job_fn, *args):
    """Each job gets its own connection/transaction so one org's failure doesn't roll back
    or block another org's job. Retries once after a short delay before giving up --
    covers transient failures (a dropped connection, a momentary lock) without masking a
    genuinely broken job, which will still fail on the retry and get logged clearly."""
    for attempt in (1, 2):
        conn = jobs.get_db()
        cur = conn.cursor()
        try:
            job_fn(cur, *args)
            conn.commit()
            return
        except Exception as e:
            conn.rollback()
            if attempt == 1:
                print(f"[scheduler] job {job_fn.__name__}{args} failed (attempt 1, retrying in {RETRY_DELAY_SECONDS}s): {e}", flush=True)
            else:
                print(f"[scheduler] job {job_fn.__name__}{args} failed (attempt 2, giving up): {e}", flush=True)
        finally:
            cur.close()
            conn.close()
        if attempt == 1:
            time.sleep(RETRY_DELAY_SECONDS)


def run_backups_for_enabled_orgs(schedule_type: str):
    conn = jobs.get_db(); cur = conn.cursor()
    org_ids = jobs.get_backup_enabled_org_ids(cur)
    cur.close(); conn.close()
    for org_id in org_ids:
        _run(jobs.run_scheduled_backup, org_id, schedule_type)
        _run(jobs.prune_org_backups, org_id)
        _run(jobs.cleanup_orphaned_snapshots, org_id)


def run_weekly_fallback_for_disabled_orgs():
    conn = jobs.get_db(); cur = conn.cursor()
    org_ids = jobs.get_backup_disabled_org_ids(cur)
    cur.close(); conn.close()
    for org_id in org_ids:
        _run(jobs.run_weekly_fallback_backup, org_id)


def run_daily_retention_pass():
    conn = jobs.get_db(); cur = conn.cursor()
    org_ids = jobs.get_all_org_ids(cur)
    cur.close(); conn.close()
    for org_id in org_ids:
        _run(jobs.prune_org_backups, org_id)
        _run(jobs.cleanup_orphaned_snapshots, org_id)


def run_gdpr_sweep():
    _run(jobs.run_gdpr_deletion_sweep)


def run_support_session_sweep():
    _run(jobs.sweep_stale_support_sessions)


JOBS = {
    "daily_backup": (run_backups_for_enabled_orgs, ["daily"]),
    "weekly_backup": (run_backups_for_enabled_orgs, ["weekly"]),
    "monthly_backup": (run_backups_for_enabled_orgs, ["monthly"]),
    "annual_backup": (run_backups_for_enabled_orgs, ["annual"]),
    "weekly_fallback": (run_weekly_fallback_for_disabled_orgs, []),
    "daily_retention": (run_daily_retention_pass, []),
    "gdpr_sweep": (run_gdpr_sweep, []),
    "support_session_sweep": (run_support_session_sweep, []),
}


def run_job_now(job_id: str):
    """API-6: manual 'run now' override, callable from main.py's POST /scheduler/run
    (platform-admin gated) without needing this process's own HTTP surface -- main.py
    imports this module and calls it directly, same DB, same job functions."""
    if job_id not in JOBS:
        raise ValueError(f"Unknown job_id '{job_id}'. Valid: {sorted(JOBS.keys())}")
    fn, args = JOBS[job_id]
    fn(*args)


def main():
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(run_backups_for_enabled_orgs, "cron", hour=2, args=["daily"], id="daily_backup")
    scheduler.add_job(run_backups_for_enabled_orgs, "cron", day_of_week="sun", hour=3, args=["weekly"], id="weekly_backup")
    scheduler.add_job(run_backups_for_enabled_orgs, "cron", day=1, hour=4, args=["monthly"], id="monthly_backup")
    scheduler.add_job(run_backups_for_enabled_orgs, "cron", month=1, day=1, hour=5, args=["annual"], id="annual_backup")

    scheduler.add_job(run_weekly_fallback_for_disabled_orgs, "cron", day_of_week="sun", hour="3", minute=30, id="weekly_fallback")
    scheduler.add_job(run_daily_retention_pass, "cron", hour=6, id="daily_retention")
    scheduler.add_job(run_gdpr_sweep, "cron", minute=0, id="gdpr_sweep")
    scheduler.add_job(run_support_session_sweep, "cron", minute=15, id="support_session_sweep")

    print("[scheduler] started, jobs registered:", [j.id for j in scheduler.get_jobs()], flush=True)
    scheduler.start()


if __name__ == "__main__":
    main()