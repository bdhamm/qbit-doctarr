from datetime import datetime
from ...database import log_task_history
from ._shared.config import calc_delta, load_config
from ._shared.qbit import QBittorrentAPI
from ._shared.arr_helpers import (
    get_all_arr_queue_hashes, filter_torrents_by_arr_category,
)
from ._shared.logging import logger, _log_full_and_truncated


def task_clean_unmanaged(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    logger.info(f"Starting Unmanaged Torrent scan (Dry Run: {is_dry_run})...")
    if not config.get("qbit", {}).get("enabled", True): return 0, "qBittorrent is disabled.", []
    unmanaged_time = float(config.get("thresholds", {}).get("unmanaged_time", 168))
    unmanaged_unit = config.get("thresholds", {}).get("unmanaged_unit", "hours")
    unmanaged_delta = calc_delta(unmanaged_time, unmanaged_unit)
    cutoff_time = datetime.now() - unmanaged_delta
    try:
        qbit = QBittorrentAPI(config)
        torrents = qbit.get_torrents()
    except Exception as e:
        logger.error(f"qBit connection failed: {e}")
        log_task_history("Unmanaged Torrents", "Error", str(e))
        return 0, str(e), []

    # STRICT CATEGORY FILTER: only torrents in a category managed by an
    # enabled *arr are candidates. Non-*arr torrents (games, ISOs, work
    # files, misc manual downloads) are never inspected.
    torrents = filter_torrents_by_arr_category(torrents, config)

    arr_map, errors = get_all_arr_queue_hashes(config)
    if errors:
        logger.error("Failed to fetch queues from one or more *Arr instances. Aborting unmanaged cleanup to prevent accidental deletion.")
        log_task_history("Unmanaged Torrents", "Error", "Failed to fetch *Arr queues. Aborting to prevent data loss.")
        return 0, "Failed to fetch *Arr queues. Aborting.", []
    orphans = []
    audit_list = []
    for t in torrents:
        t_hash = t.get("hash")
        t_name = t.get("name", "Unknown")
        added_on = t.get("added_on", 0)
        state = str(t.get("state", "")).lower()
        if not any(s in state for s in ["paused", "stopped"]): continue
        if added_on <= 0:
            audit_list.append(f"[UNMANAGED] {t_name} -> Skipping (no added_on)")
            continue
        age_hours = (datetime.now() - datetime.fromtimestamp(added_on)).total_seconds() / 3600
        arr_owner = arr_map.get(t_hash)
        if arr_owner:
            audit_list.append(f"[MANAGED by {arr_owner}] {t_name} (Age: {age_hours:.1f}h)")
        else:
            if datetime.fromtimestamp(added_on) < cutoff_time:
                audit_list.append(f"[UNMANAGED] {t_name} (Age: {age_hours:.1f}h) -> WILL DELETE")
                orphans.append({"hash": t_hash, "name": t_name})
            else:
                audit_list.append(f"[UNMANAGED] {t_name} (Age: {age_hours:.1f}h) -> Skipping (Too young)")
    audit_list.sort(reverse=True)
    orphan_names = [o["name"] for o in orphans]
    if not is_dry_run:
        for o in orphans:
            try: qbit.delete_torrent(o["hash"])
            except Exception as e: logger.error(f"Failed to delete {o['name']}: {e}")
        action_str = f"Deleted {len(orphans)} unmanaged torrents"
    else:
        action_str = f"Found {len(orphans)} unmanaged torrents to delete"
    details = _log_full_and_truncated("Unmanaged Torrents", "Success", action_str, orphan_names, is_dry_run=is_dry_run)
    return len(orphans), details, audit_list
