"""
APScheduler-based daily sync scheduler.

Runs the full case sync automatically every day at SYNC_HOUR:SYNC_MINUTE UTC
(default 06:00 UTC) so the tracker reflects the latest filings each morning.

On first startup an immediate background sync is also triggered so the
database is pre-populated without waiting until the next scheduled run.

To change the daily sync time set SYNC_HOUR and SYNC_MINUTE environment
variables (e.g. SYNC_HOUR=8 SYNC_MINUTE=30 for 08:30 UTC).
"""

import logging
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler = None


def _job(app):
    from sync import run_sync
    token = os.getenv("COURTLISTENER_API_TOKEN")
    logger.info("Scheduled daily sync starting")
    summary = run_sync(app, courtlistener_token=token)
    added = sum(v.get("added", 0) for v in summary.values())
    updated = sum(v.get("updated", 0) for v in summary.values())
    logger.info(
        "Scheduled daily sync complete — %d new cases, %d updated. Summary: %s",
        added, updated, summary,
    )


def _startup_sync(app):
    """Run an immediate sync in a background thread at startup."""
    from sync import run_sync
    token = os.getenv("COURTLISTENER_API_TOKEN")
    logger.info("Startup sync beginning (background thread)…")
    try:
        summary = run_sync(app, courtlistener_token=token)
        added = sum(v.get("added", 0) for v in summary.values())
        logger.info("Startup sync complete — %d new cases added.", added)
    except Exception as exc:
        logger.error("Startup sync failed: %s", exc)


def start(app):
    """
    Start the background scheduler and kick off an immediate startup sync.
    Call once at application startup.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    sync_hour = int(os.getenv("SYNC_HOUR", "6"))
    sync_minute = int(os.getenv("SYNC_MINUTE", "0"))

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        func=_job,
        args=[app],
        trigger=CronTrigger(hour=sync_hour, minute=sync_minute),
        id="daily_sync",
        name="Daily federal litigation sync",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — daily sync at %02d:%02d UTC", sync_hour, sync_minute
    )

    # Immediate startup sync in a daemon thread so it doesn't block the server
    t = threading.Thread(target=_startup_sync, args=(app,), daemon=True, name="startup-sync")
    t.start()


def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def trigger_now(app):
    """Manually trigger an immediate sync (used by the /api/sync endpoint)."""
    from sync import run_sync
    token = os.getenv("COURTLISTENER_API_TOKEN")
    return run_sync(app, courtlistener_token=token)
