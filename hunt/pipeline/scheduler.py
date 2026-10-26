"""In-process scheduler: runs the pipeline daily at 09:00 America/Chicago while
the server is running. For hosts where the server is not always on, use the
GitHub Actions workflow or system cron calling `hunt run --scheduled`."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from hunt.config import get_settings

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
JOB_ID = "daily-pipeline"


def _scheduled_run() -> None:
    from hunt.pipeline.runner import RunAlreadyActive, run_pipeline
    try:
        run_pipeline(trigger="schedule")
    except RunAlreadyActive as e:
        log.warning("Scheduled run skipped: %s", e)
    except Exception:  # noqa: BLE001
        log.exception("Scheduled run crashed")


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    s = get_settings()
    if not s.scheduler_enabled or _scheduler is not None:
        return _scheduler
    tz = ZoneInfo(s.timezone)
    _scheduler = BackgroundScheduler(timezone=tz)
    _scheduler.add_job(_scheduled_run, CronTrigger(hour=s.schedule_hour, minute=s.schedule_minute, timezone=tz),
                       id=JOB_ID, max_instances=1, coalesce=True, misfire_grace_time=3 * 3600, replace_existing=True)
    _scheduler.start()
    log.info("Scheduler started: daily at %02d:%02d %s", s.schedule_hour, s.schedule_minute, s.timezone)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run_time() -> datetime | None:
    s = get_settings()
    if _scheduler is not None:
        job = _scheduler.get_job(JOB_ID)
        if job and job.next_run_time:
            return job.next_run_time
    # compute even if not running in this process (e.g. GitHub Actions host)
    tz = ZoneInfo(s.timezone)
    trig = CronTrigger(hour=s.schedule_hour, minute=s.schedule_minute, timezone=tz)
    return trig.get_next_fire_time(None, datetime.now(tz))


def scheduler_running() -> bool:
    return _scheduler is not None and _scheduler.running


def run_in_background(**kwargs) -> threading.Thread:
    from hunt.pipeline.runner import RunAlreadyActive, run_pipeline

    def target():
        try:
            run_pipeline(**kwargs)
        except RunAlreadyActive as e:
            log.warning("Manual run skipped: %s", e)
        except Exception:  # noqa: BLE001
            log.exception("Background run crashed")

    t = threading.Thread(target=target, name="pipeline-run", daemon=True)
    t.start()
    return t


def is_scheduled_hour(tz_name: str | None = None) -> bool:
    """For external cron (GitHub Actions runs at both 14:00 and 15:00 UTC to cover
    DST): true only during the configured local hour."""
    s = get_settings()
    now = datetime.now(ZoneInfo(tz_name or s.timezone))
    return now.hour == s.schedule_hour
