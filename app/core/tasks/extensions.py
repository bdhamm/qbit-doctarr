from pathlib import Path
from ...database import log_task_history
from ._shared.config import load_config
from ._shared.qbit import QBittorrentAPI
from ._shared.arr_helpers import (
    fail_torrent_in_arr, filter_torrents_by_arr_category,
)
from ._shared.logging import logger, _log_full_and_truncated


def task_check_extensions(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    logger.info(f"Starting Malicious Extension scan (Dry Run: {is_dry_run})...")
    if not config.get("qbit", {}).get("enabled", True): return 0, "qBittorrent is disabled.", []
    blocklist = [ext.strip().lower().replace(".", "") for ext in config.get("thresholds", {}).get("blocked_extensions", "").split(",") if ext.strip()]
    allowlist = [ext.strip().lower().replace(".", "") for ext in config.get("thresholds", {}).get("approved_extensions", "").split(",") if ext.strip()]
    if not blocklist: return 0, "No blocked extensions configured.", []
    try:
        qbit = QBittorrentAPI(config)
        torrents = qbit.get_torrents()
    except Exception as e:
        logger.error(f"qBit connection failed: {e}")
        log_task_history("Malicious Extensions", "Error", str(e))
        return 0, str(e), []

    # STRICT CATEGORY FILTER: only inspect torrents in an *arr-managed category.
    # Non-*arr torrents are never opened, never scanned, never deleted.
    torrents = filter_torrents_by_arr_category(torrents, config)

    actioned_count = 0
    audit_list = []
    actioned_names = []
    for t in torrents:
        if float(t.get("size", 0)) == 0: continue
        t_hash = t.get("hash")
        t_name = t.get("name", "Unknown")
        try:
            files = qbit.get_torrent_files(t_hash)
            bad_indices = []
            has_good_files = False
            for i, f in enumerate(files):
                f_name = f.get("name", "")
                ext = Path(f_name).suffix.lower().replace(".", "")
                if ext in allowlist: has_good_files = True
                elif ext in blocklist and f.get("priority") != 0: bad_indices.append(i)
            if bad_indices:
                if has_good_files:
                    if not is_dry_run: qbit.set_file_priority(t_hash, bad_indices, 0)
                    audit_list.append(f"[PARTIAL] {t_name} -> Skipped {len(bad_indices)} malicious files, kept approved media")
                    actioned_names.append(t_name)
                    actioned_count += 1
                else:
                    audit_list.append(f"[DELETED] {t_name} -> No approved files found")
                    if not is_dry_run: fail_torrent_in_arr(config, t_hash, t_name, t.get("category", ""))
                    actioned_names.append(t_name)
                    actioned_count += 1
        except Exception as e:
            logger.warning(f"Extension scan failed for '{t_name}': {e}")
            audit_list.append(f"[ERROR] {t_name} -> {e}")
    action_str = f"Found {actioned_count} torrents containing malicious files" if is_dry_run else f"Actioned {actioned_count} torrents containing malicious files"
    details = _log_full_and_truncated("Malicious Extensions", "Success", action_str, actioned_names, is_dry_run=is_dry_run)
    return actioned_count, details, audit_list
