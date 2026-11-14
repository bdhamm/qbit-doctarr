"""Missing media tracking list and per-item actions."""

import json
import sqlite3
from urllib.request import Request, build_opener

from flask import request, jsonify

from ..core.tasks._shared.config import resolve_api_version
from ..core.tasks._shared.qbit import QBittorrentAPI
from ..core.tasks._shared.arr_helpers import (
    _search_command_for, _blocklist_releases_for,
)
from ..core.tasks._shared.logging import logger
from ..database import log_task_history
from ._shared import DB_PATH, load_config, _local_time
from . import bp


@bp.route('/api/missing/list')
def list_missing():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM missing_media ORDER BY status DESC, title ASC")
    items = [dict(row) for row in cursor.fetchall()]
    for row in items:
        row["last_searched"] = _local_time(row.get("last_searched"))
    conn.close()
    return jsonify(items)


def _trigger_search(arr_conf, item_id):
    """Fire the *arr search command. Raises on failure."""
    payload = _search_command_for(arr_conf, item_id)
    api_url = arr_conf["url"].rstrip("/")
    api_key = arr_conf["api_key"]
    api_ver = resolve_api_version(arr_conf.get("type", "radarr"), arr_conf.get("api_version", "auto"))
    req = Request(
        f"{api_url}/api/{api_ver}/command",
        data=json.dumps(payload).encode(),
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with build_opener().open(req, timeout=10) as resp:
        pass


def _remove_orphaned_torrents(config, payloads):
    """Remove failed torrents from qBittorrent by info hash.

    Silently skips torrents not present in qBit. Returns count removed.
    Note: delete_torrent is expected to remove files along with the torrent;
    if disk space isn't freed after this runs, that signature may need a
    delete_files flag.
    """
    if not payloads:
        return 0
    try:
        qbit = QBittorrentAPI(config)
    except Exception as e:
        logger.warning(f"qBit init failed, skipping cleanup: {e}")
        return 0

    removed = 0
    for p in payloads:
        did = p.get("download_id")
        if not did:
            continue
        try:
            qbit.delete_torrent(did.upper())
            removed += 1
            logger.info(f"Removed orphaned torrent from qBit: {p.get('source_title','?')}")
        except Exception as e:
            # qBit may reject removal if the torrent is already gone; treat as ok
            logger.debug(f"qBit remove skipped for {did[:12]}: {e}")
    return removed


def _do_action(cursor, config, item, action, dry_run=False):
    """Execute one action for one item. Returns (success_bool, message, dry_payloads).

    Does NOT commit or close the connection — caller owns that.
    """
    item_id = item["id"]
    arr_name = item["arr_name"]
    arr_item_id = item["item_id"]
    title = item["title"]

    if action == "retry":
        cursor.execute(
            "UPDATE missing_media SET status='active', attempts=0, "
            "last_searched='1970-01-01 00:00:00' WHERE id=?",
            (item_id,),
        )
        return True, f"Reset attempts for '{title}'.", None

    if action == "ignore":
        cursor.execute("UPDATE missing_media SET status='ignored' WHERE id=?", (item_id,))
        return True, f"Marked '{title}' as ignored.", None

    if action == "search_now":
        arr_conf = next((a for a in config.get("arrs", []) if a.get("name") == arr_name), None)
        if not arr_conf:
            return False, f"No *arr config matches '{arr_name}'.", None
        try:
            _trigger_search(arr_conf, arr_item_id)
            cursor.execute(
                "UPDATE missing_media SET last_searched=CURRENT_TIMESTAMP WHERE id=?",
                (item_id,),
            )
            return True, f"Search triggered for '{title}'.", None
        except Exception as e:
            return False, f"Search failed for '{title}': {e}", None

    if action == "blocklist_research":
        arr_conf = next((a for a in config.get("arrs", []) if a.get("name") == arr_name), None)
        if not arr_conf:
            return False, f"No *arr config matches '{arr_name}'.", None

        blocklisted, blocklist_error, payloads = _blocklist_releases_for(
            arr_conf, arr_item_id, dry_run=dry_run,
        )

        if dry_run:
            if blocklist_error:
                return False, f"[DRY RUN] {blocklist_error}", None
            return True, f"[DRY RUN] Would fail {len(payloads)} release(s) for '{title}'.", payloads

        # Step 2: remove orphaned torrents from qBit
        qbit_removed = _remove_orphaned_torrents(config, payloads)

        # Step 3: explicit search
        # (/history/failed blocklists but doesn't reliably trigger a search)
        search_error = None
        try:
            _trigger_search(arr_conf, arr_item_id)
        except Exception as e:
            search_error = str(e)

        cursor.execute(
            "UPDATE missing_media SET status='active', attempts=0, "
            "last_searched=CURRENT_TIMESTAMP WHERE id=?",
            (item_id,),
        )

        if search_error:
            return False, f"Blocklisted {blocklisted}, removed {qbit_removed} from qBit, but search failed: {search_error}", None

        parts = []
        if blocklisted > 0:
            parts.append(f"blocklisted {blocklisted} release(s)")
        if qbit_removed > 0:
            parts.append(f"removed {qbit_removed} torrent(s) from qBit")
        if not parts:
            parts.append("no failed releases to blocklist")
        msg = f"'{title}': " + ", ".join(parts) + "; search triggered for replacement."
        if blocklist_error:
            msg += f" (blocklist warning: {blocklist_error})"
        return True, msg, None

    return False, f"Unknown action '{action}'.", None


@bp.route('/api/missing/action', methods=['POST'])
def missing_action():
    data = request.json
    item_id = data.get('id')
    action = data.get('action')
    dry_run = bool(data.get('dry_run', False))
    config = load_config()

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM missing_media WHERE id=?", (item_id,))
    item = cursor.fetchone()
    if not item:
        conn.close()
        return jsonify({"status": "error", "message": "Item not found"}), 404

    item = dict(item)
    ok, message, dry_payloads = _do_action(cursor, config, item, action, dry_run=dry_run)
    conn.commit()
    conn.close()

    if not ok:
        return jsonify({"status": "error", "message": message}), 500
    body = {"status": "success", "message": message}
    if dry_payloads is not None:
        body["payloads"] = dry_payloads
    return jsonify(body)


@bp.route('/api/missing/bulk-action', methods=['POST'])
def missing_bulk_action():
    data = request.json or {}
    ids = data.get('ids') or []
    action = data.get('action')

    if not ids:
        return jsonify({"status": "error", "message": "No items specified."}), 400
    if action not in ('retry', 'ignore', 'blocklist_research'):
        return jsonify({"status": "error", "message": f"Action '{action}' not allowed in bulk."}), 400

    config = load_config()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    succeeded = 0
    failed = 0
    errors = []

    for item_id in ids:
        cursor.execute("SELECT * FROM missing_media WHERE id=?", (item_id,))
        row = cursor.fetchone()
        if not row:
            failed += 1
            errors.append(f"id {item_id}: not found")
            continue

        item = dict(row)
        try:
            ok, message, _ = _do_action(cursor, config, item, action, dry_run=False)
        except Exception as e:
            ok = False
            message = str(e)

        if ok:
            succeeded += 1
        else:
            failed += 1
            errors.append(f"'{item.get('title','?')}': {message}")

    conn.commit()
    conn.close()

    summary = f"Bulk {action}: {succeeded} succeeded, {failed} failed"
    if failed > 0:
        summary += f" ({len(errors)} error(s))"
    log_task_history("Missing Media Bulk", "Success", summary)

    return jsonify({
        "status": "success",
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors[:10],
        "message": summary,
    })
