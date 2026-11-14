"""Per-task timeout advisory system.

Python threads cannot be forcibly killed. This module provides a "watchdog"
pattern: the task runs synchronously in the caller's thread, and a daemon
thread waits on a cancel event. If the timeout elapses before the task
finishes, the watchdog writes a 'timeout' row to task_history. The task
continues to completion and later writes its normal success/error row,
so History shows both events in order.

Timeout of 0 = disabled (task is expected to run long and should never be
flagged). Per-task overrides can be set in config.json under the key
"task_timeouts", e.g. {"task_timeouts": {"bt_backup": 600}}.
"""

import logging
import threading

from ....database import log_task_history

logger = logging.getLogger(__name__)

# Default timeouts in seconds. 0 = never flag as timed out.
DEFAULTS = {
    "bt_backup":  300,   # 5 min  - quick orphan cleanup
    "unmanaged":  900,   # 15 min - walks the library
    "stalled":    600,   # 10 min - torrent status check
    "extensions": 600,   # 10 min - fast lookups
    "quarantine": 600,   # 10 min - directory scan
    "arr_health": 300,   # 5 min  - six quick health pings
    "missing":    0,     # no limit - observed 30+ min in production
    "unmonitor":  0,     # no limit - can hit 30+ min on large libraries
    "metrics":    60,    # 1 min  - two COUNT queries + one iterdir
}


def get_timeout(task_name, config=None):
    """Resolve the effective timeout for a task.

    Config overrides the hardcoded default. 0 means no timeout.
    Unknown tasks fall back to 600s (10 min).
    """
    if config and isinstance(config.get("task_timeouts"), dict):
        raw = config["task_timeouts"].get(task_name)
        if raw is not None:
            try:
                return int(raw)
            except (ValueError, TypeError):
                pass
    return DEFAULTS.get(task_name, 600)


def run_with_timeout(task_name, task_fn, timeout_seconds, *args, **kwargs):
    """Run task_fn. If it exceeds timeout_seconds, write an advisory
    'timeout' history row from a watchdog thread.

    The task is NOT killed. It continues running in the caller's thread
    until completion and later writes its own success/error row, so
    History shows both events. This keeps APScheduler's single-worker
    pool serialized and prevents overlap between runs.
    """
    if timeout_seconds <= 0:
        return task_fn(*args, **kwargs)

    cancel_event = threading.Event()

    def watchdog():
        if cancel_event.wait(timeout=timeout_seconds):
            return  # task finished in time - nothing to do
        try:
            log_task_history(
                task_name,
                "timeout",
                {
                    "summary": f"Still running after {timeout_seconds}s - watchdog alert (task continues)",
                    "files": [],
                    "errors": [],
                    "meta": {"timeout_seconds": timeout_seconds},
                },
            )
            logger.warning(f"Task '{task_name}' exceeded {timeout_seconds}s - timeout row written")
        except Exception as e:
            logger.error(f"Failed to write timeout row for '{task_name}': {e}")

    t = threading.Thread(target=watchdog, daemon=True, name=f"watchdog-{task_name}")
    t.start()
    try:
        return task_fn(*args, **kwargs)
    finally:
        cancel_event.set()
        t.join(timeout=2)
