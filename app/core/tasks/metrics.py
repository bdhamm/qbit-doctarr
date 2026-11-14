"""Hourly snapshot of dashboard counts for the Trends page.

Reads the same source data the dashboard's Snapshot row uses:
  Missing Media Sync   -> missing_media.status  (active / failed / ignored)
  Torrent Cleanup      -> stalled_torrents.status (dl_stall / meta_stall / seed_stall)

Writes one row per call to metrics_history and prunes rows older than
RETENTION_DAYS. `dry_run` is accepted for interface consistency with the
other task entrypoints but has no effect - a snapshot is purely observational.
"""

import sqlite3

from ...database import log_task_history
from ._shared.config import DB_PATH

RETENTION_DAYS = 30


def task_snapshot_metrics(dry_run=False):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT status, COUNT(*) FROM missing_media GROUP BY status")
    missing = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("SELECT status, COUNT(*) FROM stalled_torrents GROUP BY status")
    stalled = {row[0]: row[1] for row in cursor.fetchall()}

    m_active = missing.get("active", 0)
    m_failed = missing.get("failed", 0)
    m_ignored = missing.get("ignored", 0)
    s_dl = stalled.get("dl_stall", 0)
    s_meta = stalled.get("meta_stall", 0)
    s_seed = stalled.get("seed_stall", 0)

    cursor.execute('''
        INSERT INTO metrics_history
        (missing_active, missing_failed, missing_ignored,
         stalled_dl, stalled_meta, stalled_seed)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (m_active, m_failed, m_ignored, s_dl, s_meta, s_seed))

    cursor.execute(
        "DELETE FROM metrics_history WHERE snapshot_at < datetime('now', ?)",
        (f'-{RETENTION_DAYS} days',)
    )
    pruned = cursor.rowcount

    conn.commit()
    conn.close()

    missing_total = m_active + m_failed + m_ignored
    stalled_total = s_dl + s_meta + s_seed
    summary = f"Snapshot: {missing_total} missing, {stalled_total} stalled"
    if pruned > 0:
        summary += f" (pruned {pruned} row(s) older than {RETENTION_DAYS}d)"

    log_task_history("Metrics Snapshot", "Success", {
        "summary": summary,
        "meta": {
            "missing_active": m_active,
            "missing_failed": m_failed,
            "missing_ignored": m_ignored,
            "stalled_dl": s_dl,
            "stalled_meta": s_meta,
            "stalled_seed": s_seed,
            "pruned": pruned,
        },
    })
    return missing_total + stalled_total
