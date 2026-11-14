"""Dashboard and history aggregate stats."""

import sqlite3
from pathlib import Path

from flask import request, jsonify

from ..scheduler import get_next_runs
from ..core.tasks._shared.config import QUARANTINE_PATH
from ..database import parse_task_details
from ._shared import DB_PATH, load_config, _local_time
from . import bp


@bp.route('/api/stats')
def get_stats():
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM stalled_torrents ORDER BY first_seen DESC")
    stalled_data = [dict(row) for row in cursor.fetchall()]
    for row in stalled_data:
        row["first_seen"] = _local_time(row.get("first_seen"))
        
    cursor.execute("SELECT * FROM task_history ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
    history_data = [dict(row) for row in cursor.fetchall()]
    for row in history_data:
        row["last_run"] = _local_time(row.get("last_run"))
        parsed, display = parse_task_details(row.get("details"))
        row["details_structured"] = parsed
        row["details"] = display  # human-readable summary for the UI
        
    conn.close()
    return jsonify({"stalled": stalled_data, "history": history_data, "next_runs": get_next_runs()})


@bp.route('/api/dashboard')
def get_dashboard():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT task_name, status, details, last_run
        FROM task_history
        WHERE id IN (SELECT MAX(id) FROM task_history GROUP BY task_name)
    """)
    latest = {row["task_name"]: dict(row) for row in cursor.fetchall()}
    for name in latest:
        latest[name]["last_run"] = _local_time(latest[name].get("last_run"))
        parsed, display = parse_task_details(latest[name].get("details"))
        latest[name]["details_structured"] = parsed
        latest[name]["details"] = display

    cursor.execute("SELECT status, COUNT(*) AS c FROM missing_media GROUP BY status")
    missing_counts = {row["status"]: row["c"] for row in cursor.fetchall()}

    cursor.execute("SELECT COUNT(*) AS c FROM stalled_torrents")
    stalled_count = cursor.fetchone()["c"]

    cursor.execute("SELECT status, COUNT(*) AS c FROM stalled_torrents GROUP BY status")
    stalled_breakdown = {row["status"]: row["c"] for row in cursor.fetchall()}

    conn.close()

    q_path = Path(QUARANTINE_PATH)
    quarantine_count = sum(1 for f in q_path.iterdir() if f.is_file()) if q_path.is_dir() else 0

    live_config = load_config()
    retention_days = int(live_config.get("thresholds", {}).get("quarantine_retention_days", 7))
    hidden_cards = live_config.get("dashboard_hidden_cards", [])

    return jsonify({
        "latest_runs": latest,
        "missing_counts": missing_counts,
        "stalled_count": stalled_count,
        "stalled_breakdown": stalled_breakdown,
        "quarantine_count": quarantine_count,
        "quarantine_retention_days": retention_days,
        "dashboard_hidden_cards": hidden_cards,
        "next_runs": get_next_runs()
    })


@bp.route('/api/arr-health')
def get_arr_health():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    config = load_config()
    enabled_arrs = [a.get("name") for a in config.get("arrs", []) if a.get("enabled", True)]
    enabled_arrs.append("qbit-doctarr") # Add doctarr to the list of health sources
    enabled_set = set(enabled_arrs)

    cursor.execute("SELECT * FROM arr_health_status")
    statuses = {}
    for row in cursor.fetchall():
        if row["arr_name"] in enabled_set:
            d = dict(row)
            d["last_checked"] = _local_time(d.get("last_checked"))
            statuses[row["arr_name"]] = d

    for name in enabled_arrs:
        if name not in statuses:
            statuses[name] = {
                "arr_name": name,
                "last_checked": None,
                "last_status": "unknown",
                "last_error": None,
            }

    cursor.execute(
        "SELECT arr_name, source, severity, message, wiki_url, first_seen, last_seen "
        "FROM arr_health_warnings WHERE is_active=1 ORDER BY arr_name, source"
    )
    warnings = [dict(row) for row in cursor.fetchall() if row["arr_name"] in enabled_set]
    for w in warnings:
        w["first_seen"] = _local_time(w.get("first_seen"))
        w["last_seen"] = _local_time(w.get("last_seen"))

    cursor.execute("""
        SELECT source,
               SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active_count,
               SUM(CASE WHEN is_active=0 THEN 1 ELSE 0 END) AS inactive_count,
               MAX(last_seen) AS last_seen
        FROM arr_health_warnings
        GROUP BY source
        ORDER BY source
    """)
    sources = []
    for row in cursor.fetchall():
        d = dict(row)
        d["last_seen"] = _local_time(d.get("last_seen"))
        sources.append(d)

    conn.close()
    return jsonify({"statuses": statuses, "warnings": warnings, "sources": sources})
