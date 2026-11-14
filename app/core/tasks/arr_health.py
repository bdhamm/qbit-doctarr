"""Database Health Check.

Queries each enabled *arr's /api/{ver}/health endpoint.
Also performs a local PRAGMA integrity_check on qbit-doctarr's own SQLite DB.
For Lidarr, it additionally checks for Unmapped Files (bonus tracks/deluxe editions).

Per-arr status is derived from the response:
  - 'ok'              → reachable, no DatabaseCheck error reported (Healthy)
  - 'unreachable'     → API call failed (Unreachable)
  - 'error_warnings'  → reachable, DatabaseCheck error reported (Unhealthy)

The task itself is always Success unless it throws before/after the per-arr loop.
"""

import json
import sqlite3
from urllib.request import Request, build_opener

from ...database import DB_PATH, log_task_history
from ._shared.config import load_config, resolve_api_version
from ._shared.logging import logger

TASK_NAME = "Database Health"


def _fetch_health(arr):
    api_url = arr["url"].rstrip("/")
    api_key = arr["api_key"]
    api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
    req = Request(f"{api_url}/api/{api_ver}/health", headers={"X-Api-Key": api_key})
    with build_opener().open(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if not isinstance(data, list):
        raise ValueError(f"Unexpected /health response type: {type(data).__name__}")
    return data


def _check_lidarr_unmapped(arr):
    """Check Lidarr for unmapped files (bonus tracks, deluxe editions).

    Lidarr exposes unmapped files as a filter on the trackfile endpoint:
    GET /api/v1/trackfile?unmapped=true
    There is no standalone /api/v1/unmapped route (that returns 404).
    """
    api_url = arr["url"].rstrip("/")
    api_key = arr["api_key"]
    api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
    req = Request(
        f"{api_url}/api/{api_ver}/trackfile?unmapped=true",
        headers={"X-Api-Key": api_key},
    )
    try:
        with build_opener().open(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if isinstance(data, list) and len(data) > 0:
            return [{
                "source": "UnmappedFilesCheck",
                "type": "warning",
                "message": (
                    f"{len(data)} unmapped files found. "
                    "Check Lidarr UI (likely bonus tracks or deluxe editions)."
                ),
            }]
        return []
    except Exception as e:
        logger.warning(f"Failed to check Lidarr unmapped files: {e}")
        return [{
            "source": "UnmappedFilesCheck",
            "type": "warning",
            "message": f"Failed to check unmapped files: {e}",
        }]


def _check_doctarr_db():
    """Run a local SQLite integrity check on qbit-doctarr's own DB."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()[0]
        conn.close()
        if result == "ok":
            return "ok", []
        else:
            return "error_warnings", [{
                "source": "DatabaseCheck", "type": "error",
                "message": f"Integrity check failed: {result}"
            }]
    except Exception as e:
        return "error_warnings", [{
            "source": "DatabaseCheck", "type": "error",
            "message": f"Failed to connect/check: {e}"
        }]


def _compute_arr_status(warnings):
    for w in warnings:
        source = (w.get("source") or "").strip()
        severity = (w.get("type") or "").strip().lower()
        if source == "DatabaseCheck" and severity == "error":
            return "error_warnings"
    return "ok"


def _upsert_warnings(cursor, arr_name, warnings):
    current_keys = set()
    for w in warnings:
        source = (w.get("source") or "").strip() or "Unknown"
        severity = (w.get("type") or "warning").strip().lower()
        message = (w.get("message") or "").strip()
        wiki_url = (w.get("wikiUrl") or "").strip()
        current_keys.add((source, message))
        cursor.execute(
            """INSERT INTO arr_health_warnings
               (arr_name, source, severity, message, wiki_url, is_active)
               VALUES (?, ?, ?, ?, ?, 1)
               ON CONFLICT(arr_name, source, message) DO UPDATE SET
                 last_seen = CURRENT_TIMESTAMP,
                 severity = excluded.severity,
                 wiki_url = excluded.wiki_url,
                 is_active = 1""",
            (arr_name, source, severity, message, wiki_url),
        )
    cursor.execute(
        "SELECT id, source, message FROM arr_health_warnings WHERE arr_name=? AND is_active=1",
        (arr_name,),
    )
    for row_id, src, msg in cursor.fetchall():
        if (src, msg) not in current_keys:
            cursor.execute("UPDATE arr_health_warnings SET is_active=0 WHERE id=?", (row_id,))


def _update_status(cursor, arr_name, status, error_message=None):
    cursor.execute(
        """INSERT INTO arr_health_status
           (arr_name, last_checked, last_status, last_error)
           VALUES (?, CURRENT_TIMESTAMP, ?, ?)
           ON CONFLICT(arr_name) DO UPDATE SET
             last_checked = CURRENT_TIMESTAMP,
             last_status = excluded.last_status,
             last_error = excluded.last_error""",
        (arr_name, status, error_message),
    )


def task_check_arr_health(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    logger.info(f"Starting {TASK_NAME} (Dry Run: {is_dry_run})...")

    eligible_arrs = [a for a in config.get("arrs", []) if a.get("enabled", True)]
    
    # We always check doctarr itself
    checks = [{"name": "qbit-doctarr", "type": "doctarr", "enabled": True}] + eligible_arrs

    if is_dry_run:
        audit = []
        for item in checks:
            name = item.get("name", "Unknown")
            if item.get("type") == "doctarr":
                status, warnings = _check_doctarr_db()
                audit.append(f"[{name}] [DRY RUN] Would record status='{status}'")
                continue
            
            try:
                warnings = _fetch_health(item)
                if item.get("type") == "lidarr":
                    warnings.extend(_check_lidarr_unmapped(item))
                status = _compute_arr_status(warnings)
                audit.append(f"[{name}] [DRY RUN] Would record status='{status}' ({len(warnings)} warning(s))")
            except Exception as e:
                audit.append(f"[{name}] [DRY RUN] Would record status='unreachable' ({type(e).__name__}: {e})")
        
        msg = f"[DRY RUN] Would check {len(checks)} sources."
        log_task_history(TASK_NAME, "Success", msg)
        return len(checks), msg, audit

    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    audit = []
    counts = {"ok": 0, "unreachable": 0, "error_warnings": 0}

    for item in checks:
        name = item.get("name", "Unknown")
        
        # Handle the local doctarr check
        if item.get("type") == "doctarr":
            status, warnings = _check_doctarr_db()
            _upsert_warnings(cursor, name, warnings)
            _update_status(cursor, name, status, None)
            counts[status] += 1
            audit.append(f"[{name}] {status.upper()}")
            logger.info(f"Doctarr DB check: {status}")
            continue

        # Handle the *arr API checks
        try:
            warnings = _fetch_health(item)
            if item.get("type") == "lidarr":
                warnings.extend(_check_lidarr_unmapped(item))
            
            status = _compute_arr_status(warnings)
            _upsert_warnings(cursor, name, warnings)
            _update_status(cursor, name, status, None)
            counts[status] += 1
            
            if status == "error_warnings":
                db_msgs = [w.get("message", "") for w in warnings
                           if (w.get("source") or "") == "DatabaseCheck"
                           and (w.get("type") or "").lower() == "error"]
                detail = "; ".join(m for m in db_msgs if m) or "DB error reported"
                audit.append(f"[{name}] UNHEALTHY: {detail}")
                logger.warning(f"Arr '{name}' reports DB error: {detail}")
            else:
                audit.append(f"[{name}] {status.upper()} ({len(warnings)} warning(s))")
        except Exception as e:
            _update_status(cursor, name, "unreachable", f"{type(e).__name__}: {e}")
            counts["unreachable"] += 1
            audit.append(f"[{name}] UNREACHABLE: {e}")
            logger.warning(f"Arr '{name}' unreachable: {e}")

    conn.commit()
    conn.close()

    summary = (
        f"Checked {len(checks)} sources: "
        f"{counts['ok']} healthy, {counts['unreachable']} unreachable, "
        f"{counts['error_warnings']} unhealthy"
    )
    log_task_history(TASK_NAME, "Success", summary)
    return len(checks), summary, audit