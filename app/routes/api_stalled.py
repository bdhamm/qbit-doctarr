"""Stalled torrent bulk actions.

Single endpoint: POST /api/stalled/bulk-action.

Action: purge_research
  For each hash: calls the existing fail_torrent_in_arr helper, which does
  the full triple-action (remove from qBittorrent with files, blocklist the
  release in the matching *arr, trigger a fresh search). Then removes the
  row from the stalled_torrents tracking table.

Notes vs errors:
  fail_torrent_in_arr returns True when the torrent was found in an *arr
  queue (full flow ran) and False when it fell back to direct qBit delete
  (torrent was not in *arr queue — either already handled or manually
  removed). The False case is not a failure from the user's perspective
  (the torrent is gone), so it's counted as succeeded with a note rather
  than as failed. Real exceptions go into the errors array.
"""

import sqlite3

from flask import request, jsonify

from ..core.tasks._shared.arr_helpers import fail_torrent_in_arr
from ..core.tasks._shared.qbit import QBittorrentAPI
from ..core.tasks._shared.logging import logger
from ..database import log_task_history
from ._shared import DB_PATH, load_config
from . import bp


@bp.route('/api/stalled/bulk-action', methods=['POST'])
def stalled_bulk_action():
    data = request.json or {}
    hashes = data.get('hashes') or []
    action = data.get('action')

    if not hashes:
        return jsonify({"status": "error", "message": "No torrents specified."}), 400
    if action != 'purge_research':
        return jsonify({"status": "error", "message": f"Action '{action}' not supported."}), 400

    config = load_config()

    # Fetch qBit torrent list once for name/category lookup.
    qbit_map = {}
    try:
        qbit = QBittorrentAPI(config)
        for t in qbit.get_torrents():
            h = (t.get("hash") or "").lower()
            if h:
                qbit_map[h] = {
                    "name": t.get("name") or "Unknown",
                    "category": t.get("category") or "",
                }
    except Exception as e:
        # If qBit is unreachable, we can't resolve names/categories. Fail
        # cleanly rather than spamming fail_torrent_in_arr with empty data.
        logger.error(f"Stalled bulk: could not fetch qBit torrent list: {e}")
        return jsonify({
            "status": "error",
            "message": f"Could not fetch torrent list from qBittorrent: {e}",
            "succeeded": 0,
            "failed": len(hashes),
            "errors": [str(e)],
            "notes": [],
        }), 500

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    succeeded = 0
    failed = 0
    errors = []
    notes = []

    for h in hashes:
        h_lower = h.lower()

        # Fallback name from stalled_torrents, used if the torrent has
        # already been removed from qBit and we can't get its name from
        # the live list.
        cursor.execute("SELECT torrent_name FROM stalled_torrents WHERE hash=?", (h,))
        row = cursor.fetchone()
        fallback_name = row["torrent_name"] if row and row["torrent_name"] else h[:12]

        info = qbit_map.get(h_lower)
        if info:
            name = info["name"] or fallback_name
            category = info["category"]
        else:
            # Torrent already gone from qBit — still try to fail in *arr
            # by scanning all queues with empty category filter. If nothing
            # matches, the *arr side does nothing and direct delete no-ops.
            name = fallback_name
            category = ""

        try:
            ok = fail_torrent_in_arr(config, h, name, category)
        except Exception as e:
            failed += 1
            errors.append(f"'{name}': {e}")
            continue

        # The *arr side was attempted (either full flow or direct-delete
        # fallback). Either way, remove the tracking row so it disappears
        # from the monitor immediately.
        try:
            cursor.execute("DELETE FROM stalled_torrents WHERE hash=?", (h,))
        except Exception as db_err:
            logger.warning(f"Failed to remove {h[:12]} from stalled_torrents: {db_err}")

        succeeded += 1
        if not ok:
            notes.append(f"'{name}': removed directly (not in *arr queue)")

    conn.commit()
    conn.close()

    summary = f"Stalled Bulk purge_research: {succeeded} succeeded, {failed} failed"
    if notes:
        summary += f" ({len(notes)} direct removal(s))"
    log_task_history("Stalled Bulk", "Success", summary)

    return jsonify({
        "status": "success",
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors[:10],
        "notes": notes[:10],
        "message": summary,
    })
