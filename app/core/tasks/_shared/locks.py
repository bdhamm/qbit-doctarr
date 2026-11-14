"""Per-task concurrency guard.

Each task name has its own threading.Lock. Manual triggers (via /api/run-task)
and scheduled runs (via scheduler.py) both check the lock before starting.

Aliases: `search` and `prune` share the same lock as `missing` because they
all dispatch into task_sync_missing under the hood. An in-progress `missing`
run blocks `search` and `prune`, and vice versa. Any future task that shares
work should be added to LOCK_ALIASES here.

Lock is acquired non-blocking. Callers get TaskAlreadyRunning, not a hang.
"""

import threading


# Map task name -> lock key. Tasks not in this dict use their own name.
LOCK_ALIASES = {
    "search": "missing",
    "prune": "missing",
}

_locks = {}
_registry_lock = threading.Lock()


def _get_lock(lock_key):
    with _registry_lock:
        lock = _locks.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _locks[lock_key] = lock
        return lock


def lock_name_for(task_name):
    """Return the canonical lock key for a task name (resolves aliases)."""
    return LOCK_ALIASES.get(task_name, task_name)


class TaskAlreadyRunning(Exception):
    """Raised by acquire() when the task's lock is held.

    `requested_name` is what the caller asked for (e.g., 'search').
    `lock_name` is the actual lock key that's held (e.g., 'missing').
    The message uses `lock_name` so the error reflects reality, not the alias.
    """
    def __init__(self, requested_name, lock_name):
        self.requested_name = requested_name
        self.lock_name = lock_name
        super().__init__(f"Task '{lock_name}' is already running")


def acquire(task_name):
    """Acquire the task's lock non-blocking.

    Returns the lock object on success. Raises TaskAlreadyRunning on contention.
    Caller MUST call release(task_name) in a finally block.
    """
    lock_key = lock_name_for(task_name)
    lock = _get_lock(lock_key)
    if not lock.acquire(blocking=False):
        raise TaskAlreadyRunning(task_name, lock_key)
    return lock


def release(task_name):
    """Release the task's lock. Silent if not held (idempotent)."""
    lock_key = lock_name_for(task_name)
    lock = _get_lock(lock_key)
    try:
        lock.release()
    except RuntimeError:
        # Not held (double release, or released from non-holder). Harmless.
        pass
