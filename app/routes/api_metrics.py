"""Historical metrics endpoint for the Trends page.

Returns raw hourly snapshots from metrics_history within the requested
window. No server-side aggregation: the client buckets to daily for the
30-day view. Keeps this endpoint dumb and reusable.
"""

import sqlite3

from flask import request, jsonify

from ._shared import DB_PATH, _local_time
from . import bp


@bp.route('/api/metrics/history')
def get_metrics_history():
    try:
        days = int(request.args.get('days', 7))
    except (ValueError, TypeError):
        days = 7
    days = max(1, min(days, 30))

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT snapshot_at,
               missing_active, missing_failed, missing_ignored,
               stalled_dl, stalled_meta, stalled_seed
        FROM metrics_history
        WHERE snapshot_at >= datetime('now', ?)
        ORDER BY snapshot_at ASC
        """,
        (f'-{days} days',),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        r["snapshot_at"] = _local_time(r.get("snapshot_at"))

    return jsonify({"days": days, "history": rows})
