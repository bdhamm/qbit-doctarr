"""Periodic digest email generation."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...database import DB_PATH, log_task_history
from ._shared.config import QUARANTINE_PATH, load_config
from ._shared.logging import logger
from .notify import _send_email

TASK_NAME = "Digest"

def task_send_digest(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    notif = config.get("notifications") or {}
    digest_conf = notif.get("digest") or {}

    logger.info(f"Starting {TASK_NAME} (Dry Run: {is_dry_run})...")

    if not notif.get("enabled", False) or not digest_conf.get("enabled", False):
        msg = "Digest disabled in settings."
        log_task_history(TASK_NAME, "Success", msg)
        return 0, msg, []

    email_cfg = notif.get("email") or {}
    sections = digest_conf.get("sections", {})
    if not any(sections.values()):
        msg = "No digest sections enabled."
        log_task_history(TASK_NAME, "Success", msg)
        return 0, msg, []

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    lines = ["qbit-doctarr Weekly Digest", "========================", ""]

    if sections.get("task_activity"):
        cursor.execute("SELECT COUNT(*) as c FROM task_history WHERE last_run >= ?", (cutoff,))
        total = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(*) as c FROM task_history WHERE last_run >= ? AND status IN ('Error', 'timeout')", (cutoff,))
        fails = cursor.fetchone()["c"]
        lines.append(f"TASK ACTIVITY: {total} runs, {fails} issues.")
        if fails:
            cursor.execute("SELECT task_name, last_run, status FROM task_history WHERE last_run >= ? AND status IN ('Error', 'timeout') ORDER BY last_run DESC LIMIT 5", (cutoff,))
            for r in cursor.fetchall():
                lines.append(f"  - {r['task_name']} ({r['status']}) at {r['last_run']}")
        lines.append("")

    if sections.get("health_changes"):
        cursor.execute("SELECT COUNT(*) as c FROM arr_health_warnings WHERE first_seen >= ?", (cutoff,))
        new_w = cursor.fetchone()["c"]
        lines.append(f"HEALTH CHANGES: {new_w} new warnings detected.")
        lines.append("")

    if sections.get("current_snapshot"):
        cursor.execute("SELECT COUNT(*) as c FROM missing_media WHERE status='active'")
        missing = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(*) as c FROM stalled_torrents")
        stalled = cursor.fetchone()["c"]
        q_path = Path(QUARANTINE_PATH)
        q_count = sum(1 for f in q_path.iterdir() if f.is_file()) if q_path.is_dir() else 0
        lines.append(f"CURRENT SNAPSHOT: {missing} missing, {stalled} stalled, {q_count} quarantined.")
        lines.append("")

    conn.close()
    lines.extend(["--", "Sent by qbit-doctarr."])
    body = "\n".join(lines)

    if is_dry_run:
        msg = "[DRY RUN] Would send digest email."
        log_task_history(TASK_NAME, "Success", msg)
        return 1, msg, []

    try:
        _send_email(email_cfg, "[qbit-doctarr] Weekly Digest", body)
    except Exception as e:
        log_task_history(TASK_NAME, "Error", f"Send failed: {e}")
        return 0, f"Send failed: {e}", []

    msg = "Digest email sent."
    log_task_history(TASK_NAME, "Success", msg)
    return 1, msg, []
