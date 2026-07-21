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
"""

from apscheduler.schedulers.blocking import BlockingScheduler
import jobs


def _run(job_fn, *args):
    """Each job gets its own connection/transaction so one org's failure doesn't roll back
    or block another org's job."""
    conn = jobs.get_db()
    cur = conn.cursor()
    try:
        job_fn(cur, *args)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[scheduler] job {job_fn.__name__}{args} failed: {e}", flush=True)
    finally:
        cur.close()
        conn.close()


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


def main():
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(run_backups_for_enabled_orgs, "cron", hour=2, args=["daily"], id="daily_backup")
    scheduler.add_job(run_backups_for_enabled_orgs, "cron", day_of_week="sun", hour=3, args=["weekly"], id="weekly_backup")
    scheduler.add_job(run_backups_for_enabled_orgs, "cron", day=1, hour=4, args=["monthly"], id="monthly_backup")
    scheduler.add_job(run_backups_for_enabled_orgs, "cron", month=1, day=1, hour=5, args=["annual"], id="annual_backup")

    scheduler.add_job(run_weekly_fallback_for_disabled_orgs, "cron", day_of_week="sun", hour="3", minute=30, id="weekly_fallback")
    scheduler.add_job(run_daily_retention_pass, "cron", hour=6, id="daily_retention")
    scheduler.add_job(run_gdpr_sweep, "cron", minute=0, id="gdpr_sweep")

    print("[scheduler] started, jobs registered:", [j.id for j in scheduler.get_jobs()], flush=True)
    scheduler.start()


if __name__ == "__main__":
    main()