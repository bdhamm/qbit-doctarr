"""Missing Media Sync.

Combines the logic of searching for missing media and pruning stale rows
from the local tracking DB into a single task. 
By default, mode='both' runs prune first, then search.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from ._shared.config import DB_PATH, MISSING_PAGE_SIZE, _arr_family, load_config, resolve_api_version
from ._shared.arr_helpers import (
    _brute_force_command_for, _is_whisparr_v3, _item_title, _search_command_for,
    _fetch_wanted_missing_ids
)
from ._shared.logging import logger, _log_full_and_truncated


def _process_missing_item(arr, item, family, arr_name, cursor, is_dry_run, cutoff_time, max_retries, audit_list):
    item_id = item.get("id")
    title = _item_title(family, item)

    cursor.execute("SELECT attempts, last_searched, status FROM missing_media WHERE arr_name=? AND item_id=?", (arr_name, item_id))
    row = cursor.fetchone()

    if row:
        attempts, last_searched_str, status = row
        if status in ["ignored", "failed"]:
            return False, 0, title
        last_searched = datetime.strptime(last_searched_str, "%Y-%m-%d %H:%M:%S") if last_searched_str else datetime.min
        if last_searched > cutoff_time:
            return False, 0, title
        new_attempts = attempts + 1
        new_status = "failed" if new_attempts >= max_retries else "active"
        if not is_dry_run:
            cursor.execute("UPDATE missing_media SET attempts=?, last_searched=CURRENT_TIMESTAMP, status=?, title=? WHERE arr_name=? AND item_id=?", (new_attempts, new_status, title, arr_name, item_id))
    else:
        new_attempts = 1
        if not is_dry_run:
            cursor.execute("INSERT OR IGNORE INTO missing_media (arr_name, item_type, item_id, title, attempts) VALUES (?, ?, ?, ?, ?)", (arr_name, arr.get("type", "radarr"), item_id, title, new_attempts))

    if not is_dry_run:
        try:
            api_url = arr["url"].rstrip("/")
            api_key = arr["api_key"]
            api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
            req = Request(f"{api_url}/api/{api_ver}/command",
                          data=json.dumps(_search_command_for(arr, item_id)).encode(),
                          headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                          method="POST")
            with build_opener().open(req, timeout=10) as resp: pass
            audit_list.append(f"[{arr_name}] Searched: {title} (Attempt {new_attempts})")
        except Exception as e:
            audit_list.append(f"[{arr_name}] ERROR searching: {e}")
    else:
        audit_list.append(f"[{arr_name}] [DRY RUN] Would search: {title}")

    return True, new_attempts, title


def _prune_missing_rows(cursor, config, is_dry_run):
    pruned_count = 0
    audit_list = []
    for arr in config.get("arrs", []):
        if not arr.get("enabled", True): continue
        arr_name = arr.get("name", "Unknown *Arr")
        api_url = arr["url"].rstrip("/")
        api_key = arr["api_key"]
        api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
        try:
            current_ids, may_be_truncated = _fetch_wanted_missing_ids(arr, api_ver, api_url, api_key, max_pages=200)
        except Exception as e:
            logger.error(f"Failed to fetch missing media for {arr_name}: {e}")
            audit_list.append(f"[{arr_name}] ERROR fetching list: {e}")
            continue
        if may_be_truncated:
            audit_list.append(f"[{arr_name}] Skipped pruning — wanted/missing was truncated at {MISSING_PAGE_SIZE * 200} items.")
            continue
        if is_dry_run:
            if current_ids:
                cursor.execute("CREATE TEMP TABLE IF NOT EXISTS _prune_ids (id INTEGER)")
                cursor.execute("DELETE FROM _prune_ids")
                cursor.executemany("INSERT INTO _prune_ids (id) VALUES (?)", [(i,) for i in current_ids])
                cursor.execute("SELECT COUNT(*) FROM missing_media WHERE arr_name=? AND item_id NOT IN (SELECT id FROM _prune_ids)", (arr_name,))
                would_prune = cursor.fetchone()[0]
            else:
                cursor.execute("SELECT COUNT(*) FROM missing_media WHERE arr_name=?", (arr_name,))
                would_prune = cursor.fetchone()[0]
            if would_prune > 0:
                audit_list.append(f"[{arr_name}] [DRY RUN] Would prune {would_prune} stale row(s).")
        else:
            if current_ids:
                cursor.execute("CREATE TEMP TABLE IF NOT EXISTS _prune_ids (id INTEGER)")
                cursor.execute("DELETE FROM _prune_ids")
                cursor.executemany("INSERT INTO _prune_ids (id) VALUES (?)", [(i,) for i in current_ids])
                cursor.execute("DELETE FROM missing_media WHERE arr_name=? AND item_id NOT IN (SELECT id FROM _prune_ids)", (arr_name,))
            else:
                cursor.execute("DELETE FROM missing_media WHERE arr_name=?", (arr_name,))
            pruned = cursor.rowcount
            if pruned > 0:
                audit_list.append(f"[{arr_name}] Pruned {pruned} stale row(s).")
                pruned_count += pruned
    return pruned_count, audit_list


def _search_missing_items(cursor, config, is_dry_run):
    thresh = config.get("thresholds", {})
    polite_mode = thresh.get("missing_polite_mode", True)
    batch_size = int(thresh.get("missing_batch_size", 3))
    batch_mode = thresh.get("missing_batch_mode", "per_arr")
    cooldown_hours = int(thresh.get("missing_cooldown_hours", 24))
    max_retries = int(thresh.get("missing_max_retries", 5))

    actioned_count = 0
    audit_list = []
    actioned_names = []
    searched = 0

    for arr in config.get("arrs", []):
        if not arr.get("enabled", True) or not arr.get("search_missing", True): continue
        arr_name = arr.get("name", "Unknown *Arr")
        api_url = arr["url"].rstrip("/")
        api_key = arr["api_key"]
        api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
        family = _arr_family(arr)

        if not polite_mode:
            cmd_name, cmd_desc = _brute_force_command_for(arr)
            if not cmd_name: continue
            if is_dry_run:
                audit_list.append(f"[{arr_name}] [DRY RUN] Would trigger FULL-LIBRARY search ({cmd_name}).")
                actioned_count += 1
                continue
            try:
                req = Request(f"{api_url}/api/{api_ver}/command", data=json.dumps({"name": cmd_name}).encode(), headers={"X-Api-Key": api_key, "Content-Type": "application/json"}, method="POST")
                with build_opener().open(req, timeout=10) as resp: pass
                audit_list.append(f"[{arr_name}] Triggered FULL-LIBRARY search ({cmd_name}).")
                actioned_count += 1
            except Exception as e:
                audit_list.append(f"[{arr_name}] ERROR triggering search: {e}")
            continue

        if batch_mode == "per_arr": searched = 0
        cutoff_time = datetime.utcnow() - timedelta(hours=cooldown_hours)
        page_processed_any = False

        if _is_whisparr_v3(arr):
            try:
                url = f"{api_url}/api/{api_ver}/movie"
                req = Request(url, headers={"X-Api-Key": api_key})
                with build_opener().open(req, timeout=30) as resp:
                    raw = json.loads(resp.read())
                movies = raw if isinstance(raw, list) else raw.get("records", [])
                page_records = [m for m in movies if m.get("monitored", False) and not m.get("hasFile", False)]
            except Exception as e:
                audit_list.append(f"[{arr_name}] ERROR fetching list: {e}")
                continue

            for item in page_records:
                if searched >= batch_size: break
                actioned, _na, title = _process_missing_item(arr, item, family, arr_name, cursor, is_dry_run, cutoff_time, max_retries, audit_list)
                if actioned:
                    searched += 1
                    actioned_count += 1
                    actioned_names.append(title)
                    page_processed_any = True
        else:
            for page_num in range(1, 6):
                try:
                    params = urlencode({"page": page_num, "pageSize": MISSING_PAGE_SIZE, "includeSeries": "true"})
                    url = f"{api_url}/api/{api_ver}/wanted/missing?{params}"
                    req = Request(url, headers={"X-Api-Key": api_key})
                    with build_opener().open(req, timeout=10) as resp:
                        data = json.loads(resp.read())
                    raw_records = data.get("records", [])
                    page_records = [r for r in raw_records if r.get("monitored", True) and not r.get("hasFile", False)]
                except Exception as e:
                    audit_list.append(f"[{arr_name}] ERROR fetching list (page {page_num}): {e}")
                    break

                for item in page_records:
                    if searched >= batch_size: break
                    actioned, _na, title = _process_missing_item(arr, item, family, arr_name, cursor, is_dry_run, cutoff_time, max_retries, audit_list)
                    if actioned:
                        searched += 1
                        actioned_count += 1
                        actioned_names.append(title)
                        page_processed_any = True

                if searched >= batch_size: break
                if len(raw_records) < MISSING_PAGE_SIZE: break

        if not page_processed_any:
            logger.info(f"[{arr_name}] No eligible items on this run (all in cooldown, ignored, or failed).")

    return actioned_count, audit_list, actioned_names


def task_sync_missing(dry_run=False, mode='both'):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    logger.info(f"Starting Missing Media Sync (Mode: {mode}, Dry Run: {is_dry_run})...")
    
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    
    pruned_count = 0
    actioned_count = 0
    full_audit = []
    full_actioned_names = []

    if mode in ('both', 'prune'):
        p_count, p_audit = _prune_missing_rows(cursor, config, is_dry_run)
        pruned_count += p_count
        full_audit.extend(p_audit)

    if mode in ('both', 'search'):
        s_count, s_audit, s_names = _search_missing_items(cursor, config, is_dry_run)
        actioned_count += s_count
        full_audit.extend(s_audit)
        full_actioned_names.extend(s_names)

    conn.commit()
    conn.close()

    polite_mode = config.get("thresholds", {}).get("missing_polite_mode", True)

    if mode == 'prune':
        action_str = f"Would prune {pruned_count} stale row(s)" if is_dry_run else f"Pruned {pruned_count} stale row(s)"
        details = _log_full_and_truncated("Missing Media Sync", "Success", action_str, [], is_dry_run=is_dry_run)
        return pruned_count, details, full_audit
    elif mode == 'search':
        if not polite_mode:
            action_str = f"Would trigger full-library search on {actioned_count} *arr(s)" if is_dry_run else f"Triggered full-library search on {actioned_count} *arr(s)"
            details = _log_full_and_truncated("Missing Media Sync", "Success", action_str, [], is_dry_run=is_dry_run)
        else:
            action_str = f"Would search {actioned_count} items" if is_dry_run else f"Searched {actioned_count} items"
            details = _log_full_and_truncated("Missing Media Sync", "Success", action_str, full_actioned_names, is_dry_run=is_dry_run)
        return actioned_count, details, full_audit
    else:
        # both
        if not polite_mode:
            action_str = f"Would prune {pruned_count} rows, trigger full-library search on {actioned_count} *arr(s)" if is_dry_run else f"Pruned {pruned_count} rows, triggered full-library search on {actioned_count} *arr(s)"
            details = _log_full_and_truncated("Missing Media Sync", "Success", action_str, [], is_dry_run=is_dry_run)
        else:
            action_str = f"Would prune {pruned_count} rows, search {actioned_count} items" if is_dry_run else f"Pruned {pruned_count} rows, searched {actioned_count} items"
            details = _log_full_and_truncated("Missing Media Sync", "Success", action_str, full_actioned_names, is_dry_run=is_dry_run)
        return pruned_count + actioned_count, details, full_audit