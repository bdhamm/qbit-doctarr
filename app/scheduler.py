import json
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.triggers.cron import CronTrigger

from .core.tasks import (
    task_clean_bt_backup, task_check_stalled, task_clean_unmanaged,
    task_check_extensions, task_cleanup_quarantine, task_unmonitor_items,
    task_check_arr_health, task_sync_missing, task_send_notifications,
    task_send_digest, task_snapshot_metrics,
)
from .core.tasks._shared.timeouts import run_with_timeout, get_timeout
from .core.tasks._shared import locks as task_lock

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(1)},
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
)
CONFIG_PATH = "/config/config.json"

def load_config():
    try:
        with open(CONFIG_PATH, 'r') as f: return json.load(f)
    except Exception: return {}

def calc_seconds(val, unit):
    if unit == "minutes": return float(val) * 60
    return float(val) * 3600

def _missing_both(): return task_sync_missing(mode='both')

def _make_wrapped(task_name, task_func, timeout_seconds):
    def _wrapped():
        try: task_lock.acquire(task_name)
        except task_lock.TaskAlreadyRunning:
            logger.warning(f"Skipping scheduled '{task_name}' — previous run still in progress")
            return
        try: return run_with_timeout(task_name, task_func, timeout_seconds)
        finally: task_lock.release(task_name)
    _wrapped.__name__ = f"wrapped_{task_name}"
    return _wrapped

def _get_existing_interval(job_id):
    job = scheduler.get_job(job_id)
    if not job: return None
    try: return job.trigger.interval.total_seconds()
    except Exception: return None

def update_schedules():
    config = load_config()
    if not config.get("schedules_enabled", True):
        logger.info("Automation Schedules are DISABLED via settings. Removing all jobs.")
        scheduler.remove_all_jobs()
        return

    schedules = config.get("schedules", {})
    bt_sec = calc_seconds(schedules.get("bt_backup_time", 24), schedules.get("bt_backup_unit", "hours"))
    stall_sec = calc_seconds(schedules.get("stalled_time", 1), schedules.get("stalled_unit", "hours"))
    unmanaged_sec = calc_seconds(schedules.get("unmanaged_time", 24), schedules.get("unmanaged_unit", "hours"))
    extensions_sec = calc_seconds(schedules.get("extensions_time", 0.5), schedules.get("extensions_unit", "hours"))
    missing_sec = calc_seconds(schedules.get("missing_time", 6), schedules.get("missing_unit", "hours"))
    quarantine_sec = calc_seconds(schedules.get("quarantine_time", 24), schedules.get("quarantine_unit", "hours"))
    unmonitor_sec = calc_seconds(schedules.get("unmonitor_time", 24), schedules.get("unmonitor_unit", "hours"))
    arr_health_sec = calc_seconds(schedules.get("arr_health_time", 6), schedules.get("arr_health_unit", "hours"))
    notify_sec = calc_seconds(schedules.get("notify_time", 0.25), schedules.get("notify_unit", "hours"))
    metrics_sec = calc_seconds(schedules.get("metrics_time", 1), schedules.get("metrics_unit", "hours"))

    timeouts = {name: get_timeout(name, config) for name in ("bt_backup", "unmanaged", "stalled", "extensions", "quarantine", "arr_health", "missing", "unmonitor", "notify", "digest", "metrics")}

    jobs = [
        ("bt_backup", task_clean_bt_backup, bt_sec),
        ("stalled", task_check_stalled, stall_sec),
        ("unmanaged", task_clean_unmanaged, unmanaged_sec),
        ("extensions", task_check_extensions, extensions_sec),
        ("missing", _missing_both, missing_sec),
        ("quarantine", task_cleanup_quarantine, quarantine_sec),
        ("unmonitor", task_unmonitor_items, unmonitor_sec),
        ("arr_health", task_check_arr_health, arr_health_sec),
        ("notify", task_send_notifications, notify_sec),
        ("metrics", task_snapshot_metrics, metrics_sec),
    ]

    changes = 0
    for job_id, func, seconds in jobs:
        existing = _get_existing_interval(job_id)
        timeout_seconds = timeouts.get(job_id, 600)
        wrapped = _make_wrapped(job_id, func, timeout_seconds)

        if seconds <= 0:
            if existing is not None:
                scheduler.remove_job(job_id)
                changes += 1
            continue

        if existing is None:
            scheduler.add_job(func=wrapped, trigger="interval", seconds=seconds, id=job_id, name=job_id)
            changes += 1
        elif abs(existing - seconds) > 0.5:
            try: scheduler.modify_job(job_id, func=wrapped, trigger="interval", seconds=seconds, name=job_id)
            except Exception:
                scheduler.remove_job(job_id)
                scheduler.add_job(func=wrapped, trigger="interval", seconds=seconds, id=job_id, name=job_id)
            changes += 1
        else:
            scheduler.modify_job(job_id, func=wrapped, name=job_id)

    # Digest (Cron)
    digest_conf = config.get("notifications", {}).get("digest", {})
    digest_enabled = digest_conf.get("enabled", False) and config.get("notifications", {}).get("enabled", False)
    digest_job = scheduler.get_job("digest")
    
    if not digest_enabled:
        if digest_job:
            scheduler.remove_job("digest")
            changes += 1
    else:
        freq = digest_conf.get("frequency", "weekly")
        hour = int(digest_conf.get("hour", 8))
        dow = int(digest_conf.get("day_of_week", 0))
        dom = int(digest_conf.get("day_of_month", 1))
        
        trigger = None
        if freq == "daily": trigger = CronTrigger(hour=hour, minute=0)
        elif freq == "weekly": trigger = CronTrigger(day_of_week=dow, hour=hour, minute=0)
        elif freq == "monthly": trigger = CronTrigger(day=dom, hour=hour, minute=0)

        timeout = timeouts.get("digest", 120)
        wrapped = _make_wrapped("digest", task_send_digest, timeout)

        if trigger:
            if not digest_job:
                scheduler.add_job(func=wrapped, trigger=trigger, id="digest", name="digest")
                changes += 1
            else:
                # Always update the trigger. If we only update the function, changes
                # to the hour/day settings won't take effect until the job is deleted.
                try:
                    scheduler.modify_job("digest", func=wrapped, trigger=trigger, name="digest")
                    changes += 1
                except Exception as e:
                    logger.warning(f"Failed to modify digest job: {e}")
                    scheduler.remove_job("digest")
                    scheduler.add_job(func=wrapped, trigger=trigger, id="digest", name="digest")

    if changes > 0: logger.info(f"Applied {changes} schedule change(s).")

def get_next_runs():
    next_runs = {}
    now = datetime.now(timezone.utc)
    for job in scheduler.get_jobs():
        if job.next_run_time:
            delta = (job.next_run_time - now).total_seconds()
            next_runs[job.id] = max(0, int(delta))
    return next_runs

def start_scheduler():
    update_schedules()
    if not scheduler.running: scheduler.start()
