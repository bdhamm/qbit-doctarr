import sqlite3
from datetime import datetime
from ...database import log_task_history
from ._shared.config import DB_PATH, calc_delta, load_config
from ._shared.qbit import QBittorrentAPI
from ._shared.arr_helpers import fail_torrent_in_arr
from ._shared.logging import logger, _log_full_and_truncated


def task_check_stalled(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    logger.info(f"Starting Stalled Tracker (Dry Run: {is_dry_run})...")
    if not config.get("qbit", {}).get("enabled", True): return 0, 0
    
    # Build a set of valid *arr categories to ignore anything else in qBittorrent
    valid_categories = set()
    for arr in config.get("arrs", []):
        if arr.get("enabled", True) and arr.get("category"):
            valid_categories.add(arr.get("category"))

    thresh = config.get("thresholds", {})
    meta_delta = calc_delta(thresh.get("meta_time", 2), thresh.get("meta_unit", "hours"))
    stalled_delta = calc_delta(thresh.get("stalled_time", 48), thresh.get("stalled_unit", "hours"))
    speed_val = float(thresh.get("slow_speed_val", 10))
    speed_unit = thresh.get("slow_speed_unit", "KiB")
    speed_multiplier = 1024 * 1024 if speed_unit == "MiB" else 1024
    speed_bytes = speed_val * speed_multiplier
    max_progress_float = float(thresh.get("max_percentage", 100)) / 100.0
    target_100_seeds = thresh.get("target_100_seeds", False)
    
    try:
        qbit = QBittorrentAPI(config)
        torrents = qbit.get_torrents()
    except Exception as e:
        logger.error(f"qBit connection failed: {e}")
        log_task_history("Stalled Tracker", "Error", str(e))
        return 0, 0
        
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    now = datetime.utcnow()
    cutoff_meta = now - meta_delta
    cutoff_stalled = now - stalled_delta
    
    cursor.execute("SELECT hash, first_seen, status FROM stalled_torrents")
    db_records = {row[0]: {"first_seen": row[1], "status": row[2]} for row in cursor.fetchall()}
    
    active_stalled_hashes = []
    actioned_count = 0
    actioned_names = []
    
    for t in torrents:
        t_hash = t.get("hash")
        t_name = t.get("name", "Unknown")
        t_category = t.get("category", "")
        
        # STRICT CATEGORY FILTER: Only process torrents managed by an *arr
        if t_category not in valid_categories:
            continue

        state = str(t.get("state", "")).lower()
        progress = float(t.get("progress") or 0)
        dlspeed = int(t.get("dlspeed") or 0)
        upspeed = int(t.get("upspeed") or 0)
        
        if "paused" in state or "stopped" in state:
            continue
            
        current_status = None
        if progress >= 1.0:
            if not target_100_seeds: continue
            if upspeed == 0: current_status = "seed_stall"
        else:
            if progress >= max_progress_float: continue
            
            # Skip queued torrents; they are just waiting their turn and aren't dead
            if "queued" in state:
                continue
                
            is_forced = "forced" in state or t.get("force_start", False)
            is_native_stall = "stalled" in state or "meta" in state
            
            # Process if it's Force-Started (custom tracking) OR natively Stalled by qBittorrent
            if not (is_forced or is_native_stall): 
                continue
                
            if "meta" in state: 
                current_status = "meta_stall"
            elif dlspeed < speed_bytes: 
                current_status = "dl_stall"
            
        if not current_status: continue
        
        active_stalled_hashes.append(t_hash)
        
        if t_hash not in db_records:
            cursor.execute("INSERT INTO stalled_torrents (hash, torrent_name, status) VALUES (?, ?, ?)", (t_hash, t_name, current_status))
            logger.info(f"New {current_status} detected: '{t_name}'. Timer started.")
        else:
            record = db_records[t_hash]
            first_seen = datetime.strptime(record["first_seen"], "%Y-%m-%d %H:%M:%S")
            if record["status"] != current_status:
                cursor.execute("UPDATE stalled_torrents SET first_seen = CURRENT_TIMESTAMP, status = ?, torrent_name = ? WHERE hash = ?", (current_status, t_name, t_hash))
                logger.info(f"Stall status changed for '{t_name}' ({record['status']} -> {current_status}). Timer reset.")
                continue
                
            is_expired = False
            if current_status == "meta_stall" and first_seen < cutoff_meta: is_expired = True
            elif current_status in ["dl_stall", "seed_stall"] and first_seen < cutoff_stalled: is_expired = True
            
            if is_expired:
                logger.warning(f"TIMEOUT REACHED ({current_status}): '{t_name}'.")
                if is_dry_run:
                    logger.info(f"[DRY RUN] Would have actioned '{t_name}'.")
                else:
                    if current_status == "seed_stall":
                        logger.info(f"Pausing completed seed '{t_name}' so the *Arr can process it.")
                        try: qbit.stop_torrent(t_hash)
                        except Exception as e: logger.error(f"Failed to pause '{t_name}': {e}")
                    else:
                        fail_torrent_in_arr(config, t_hash, t_name, t_category)
                if not is_dry_run:
                    cursor.execute("DELETE FROM stalled_torrents WHERE hash = ?", (t_hash,))
                actioned_count += 1
                actioned_names.append(t_name)
            else:
                hours_elapsed = (now - first_seen).total_seconds() / 3600
                logger.info(f"Torrent '{t_name}' is still in {current_status} timeout ({hours_elapsed:.1f}h elapsed).")
                
    for old_hash in list(db_records.keys()):
        if old_hash not in active_stalled_hashes:
            cursor.execute("DELETE FROM stalled_torrents WHERE hash = ?", (old_hash,))
            
    conn.commit()
    conn.close()
    
    action_str = f"Would action {actioned_count} torrents" if is_dry_run else f"Actioned {actioned_count} torrents"
    extra = f". Monitoring {len(active_stalled_hashes)} active stalls"
    _log_full_and_truncated("Stalled Tracker", "Success", action_str, actioned_names, is_dry_run=is_dry_run, extra_suffix=extra)
    return len(torrents), len(active_stalled_hashes)
