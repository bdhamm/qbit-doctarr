import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from .config import _arr_family, resolve_api_version, MISSING_PAGE_SIZE
from .qbit import QBittorrentAPI
from .logging import logger

_opener = build_opener()


def get_valid_categories(config):
    """Return the set of categories managed by enabled *arrs.

    Every task that reads or mutates qBittorrent state must restrict its
    working set to torrents whose category is in this set. An empty set
    means "no *arr categories are configured" — tasks should treat that
    as "do nothing" rather than "process everything".
    """
    cats = set()
    for arr in config.get("arrs", []):
        if arr.get("enabled", True) and arr.get("category"):
            cats.add(arr.get("category"))
    return cats


def filter_torrents_by_arr_category(torrents, config):
    """Return only torrents whose category is managed by an enabled *arr.

    Torrents with an empty or missing category are excluded. Torrents in
    manual/downloaded-elsewhere categories (games, ISOs, work files) are
    excluded. This is the ONLY correct way for a task to iterate the
    qBittorrent torrent list.
    """
    valid = get_valid_categories(config)
    if not valid:
        return []
    return [t for t in torrents if t.get("category") in valid]


def _search_command_for(arr, item_id):
    family = _arr_family(arr)
    if family == "radarr":
        return {"name": "MoviesSearch", "movieIds": [item_id]}
    if family == "sonarr":
        return {"name": "EpisodeSearch", "episodeIds": [item_id]}
    if family == "lidarr":
        return {"name": "AlbumSearch", "albumIds": [item_id]}
    if family in ("readarr", "chaptarr"):
        return {"name": "BookSearch", "bookIds": [item_id]}
    raise ValueError(f"Unsupported *arr type: {arr.get('type')}")


def _brute_force_command_for(arr):
    family = _arr_family(arr)
    if family == "radarr":
        return "MissingMoviesSearch", "all missing movies"
    if family == "sonarr":
        return "MissingEpisodeSearch", "all missing episodes"
    if family == "lidarr":
        return "MissingAlbumSearch", "all missing albums"
    if family in ("readarr", "chaptarr"):
        return "MissingBookSearch", "all missing books"
    return None, None


def _item_title(family, item):
    title = (item.get("title") or "").strip()
    s_num = item.get("seasonNumber")
    e_num = item.get("episodeNumber")
    if s_num is None: s_num = item.get("sceneSeasonNumber")
    if e_num is None: e_num = item.get("sceneEpisodeNumber")

    if family == "sonarr":
        series_data = item.get("series") or {}
        series_title = (series_data.get("title") or "").strip()
        tag = ""
        if s_num is not None and e_num is not None:
            try: tag = f"S{int(s_num):02d}E{int(e_num):02d}"
            except (TypeError, ValueError): pass
        parts = []
        if series_title: parts.append(series_title)
        if tag: parts.append(tag)
        if title and not title.isdigit(): parts.append(title)
        return " - ".join(parts) if parts else (title or "Unknown")

    if family == "radarr":
        parts = [title] if title else []
        if s_num is not None and e_num is not None:
            try:
                tag = f"S{int(s_num):02d}E{int(e_num):02d}"
                parts.insert(0, tag)
            except (TypeError, ValueError): pass
        return " - ".join(parts) if parts else "Unknown"

    if family == "lidarr":
        a = item.get("artist") or {}
        artist = (a.get("artistName") or "").strip()
        if artist and title: return f"{artist} - {title}"
        if artist: return artist
    if family in ("readarr", "chaptarr"):
        a = item.get("author") or {}
        author = (a.get("authorName") or "").strip()
        if author and title: return f"{author} - {title}"
        if author: return author
    return title or "Unknown"


def _is_whisparr_v3(arr):
    return (
        arr.get("type", "").lower() == "whisparr"
        and (arr.get("whisparr_version") or "v3").lower() == "v3"
    )


def _fetch_wanted_missing_ids(arr, api_ver, api_url, api_key, max_pages=200):
    ids = set()

    if _is_whisparr_v3(arr):
        url = f"{api_url}/api/{api_ver}/movie"
        req = Request(url, headers={"X-Api-Key": api_key})
        with _opener.open(req, timeout=30) as resp:
            raw = json.loads(resp.read())
        movies = raw if isinstance(raw, list) else raw.get("records", [])
        for m in movies:
            if m.get("monitored", False) and not m.get("hasFile", False) and m.get("id") is not None:
                ids.add(m["id"])
        return ids, False

    for page in range(1, max_pages + 1):
        params = urlencode({"page": page, "pageSize": MISSING_PAGE_SIZE, "includeSeries": "true"})
        url = f"{api_url}/api/{api_ver}/wanted/missing?{params}"
        req = Request(url, headers={"X-Api-Key": api_key})
        with _opener.open(req, timeout=10) as resp:
            data = json.loads(resp.read())
        raw_records = data.get("records", [])
        for r in raw_records:
            if r.get("monitored", True) and not r.get("hasFile", False) and r.get("id") is not None:
                ids.add(r["id"])
        if len(raw_records) < MISSING_PAGE_SIZE:
            return ids, False
    return ids, True


def get_all_arr_queue_hashes(config):
    arr_map = {}
    errors = False
    for arr in config.get("arrs", []):
        if not arr.get("enabled", True): continue
        api_url = arr["url"].rstrip("/")
        api_key = arr["api_key"]
        arr_name = arr.get("name", "Unknown *Arr")
        api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
        try:
            req = Request(f"{api_url}/api/{api_ver}/queue?pageSize=2500", headers={"X-Api-Key": api_key})
            with _opener.open(req, timeout=10) as resp:
                data = json.loads(resp.read())
                for r in data.get("records", []):
                    if r.get("downloadId"): arr_map[r["downloadId"].lower()] = arr_name
        except Exception as e:
            logger.error(f"Failed to fetch queue for {arr['name']}: {e}")
            errors = True
    return arr_map, errors


def fail_torrent_in_arr(config, t_hash, t_name, category):
    """Ask the *arr to blocklist + remove a torrent, or fall back to direct
    qBittorrent deletion.

    SAFETY: If the torrent's category is not managed by any enabled *arr,
    this function refuses to delete. It logs and returns. This is defense
    in depth — callers should already filter by arr category, but if a
    future caller forgets, this guard prevents non-*arr data loss.
    """
    arr_found = False
    for arr in config.get("arrs", []):
        if not arr.get("enabled", True): continue
        api_url = arr["url"].rstrip("/")
        api_key = arr["api_key"]
        arr_cat = arr.get("category", "").strip()
        api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
        if arr_cat and category != arr_cat: continue
        try:
            q_req = Request(f"{api_url}/api/{api_ver}/queue?pageSize=1000", headers={"X-Api-Key": api_key})
            with _opener.open(q_req, timeout=10) as resp: q_data = json.loads(resp.read())
            for r in q_data.get("records", []):
                if r.get("downloadId", "").lower() == t_hash.lower():
                    arr_found = True
                    del_url = f"{api_url}/api/{api_ver}/queue/{r['id']}?removeFromClient=true&blocklist=true"
                    del_req = Request(del_url, method="DELETE", headers={"X-Api-Key": api_key})
                    with _opener.open(del_req, timeout=10) as d_resp:
                        logger.info(f"Successfully triggered *arr blocklist & search for '{t_name}' in {arr['name']}")
                    break
        except Exception as e: logger.error(f"Failed to contact {arr['name']}: {e}")
    if not arr_found:
        # DEFENSE IN DEPTH: refuse direct deletion for non-*arr torrents.
        if category not in get_valid_categories(config):
            logger.warning(
                f"Torrent '{t_name}' not found in any *arr queue, and its category "
                f"{category!r} is not managed by any enabled *arr. "
                f"Skipping direct deletion (non-*arr torrent)."
            )
            return False
        logger.warning(f"Torrent '{t_name}' not found in any *arr queue. Falling back to direct deletion...")
        try:
            qbit = QBittorrentAPI(config)
            qbit.delete_torrent(t_hash)
        except Exception as e: logger.error(f"Failed to delete directly: {e}")
    return arr_found


# ---------------------------------------------------------------------------
# [Task 6.5] Blocklist / re-search for missing items
#
# Missing items aren't in the *arr queue, so the queue DELETE path used by
# fail_torrent_in_arr doesn't apply. Instead:
#
#   1. Fetch the item's history via the per-family endpoint. Radarr/Sonarr/etc.
#      IGNORE query params on the base /history endpoint -- the filter only
#      works via dedicated endpoints: /history/movie, /history/episode, etc.
#      CONFIRMED against Radarr: /api/v3/history/movie?movieId=X filters correctly.
#
#   2. Find `downloadFailed` events within the last N days. Each has a
#      `downloadId` but no guid/indexerId.
#
#   3. Correlate each failed event to its originating `grabbed` event via
#      `downloadId`. The grab has the history record `id` we need.
#
#   4. POST /api/vX/history/failed/{grab_id} for each correlated grab.
#      This is the same endpoint the *arr UI uses for "Mark as Failed".
#      It blocklists the release, but does NOT remove the torrent from
#      qBittorrent, and does NOT reliably trigger a replacement search.
#      Caller is responsible for both (see api_missing.py blocklist_research).
#
#   5. Pacing: each /history/failed POST may cause the *arr to reach out to
#      Prowlarr/indexers again. On public indexers this is fine; on private
#      indexers a burst of POSTs can look like abuse. A 200ms sleep between
#      POSTs smooths the load without noticeable delay on typical items
#      (5-20 failures = 1-4 seconds extra).
# ---------------------------------------------------------------------------

# Per-family history endpoint + query param. item_id is the id we track
# in missing_media for that family.
_HISTORY_ENDPOINT = {
    "radarr":   ("movie",    "movieId"),
    "whisparr": ("movie",    "movieId"),
    "sonarr":   ("episode",  "episodeId"),
    "lidarr":   ("album",    "albumId"),
    "readarr":  ("book",     "bookId"),
    "chaptarr": ("book",     "bookId"),
}

# How far back to look for failed releases to blocklist.
_BLOCKLIST_WINDOW_DAYS = 30

# Delay between /history/failed POSTs to avoid hammering Prowlarr/indexers.
_BLOCKLIST_POST_DELAY = 0.2


def _fetch_item_history(arr, item_id):
    """Fetch recent history for one *arr item. Returns (records, error)."""
    family = _arr_family(arr)
    api_url = arr["url"].rstrip("/")
    api_key = arr["api_key"]
    api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))

    sub, param = _HISTORY_ENDPOINT.get(family, (None, None))
    if not sub or not param:
        return [], f"No history endpoint defined for family '{family}'"

    try:
        url = f"{api_url}/api/{api_ver}/history/{sub}?{param}={item_id}"
        req = Request(url, headers={"X-Api-Key": api_key})
        with _opener.open(req, timeout=15) as resp:
            data = json.loads(resp.read())
        records = data.get("records", []) if isinstance(data, dict) else data
        return records, None
    except Exception as e:
        return [], f"History fetch failed: {e}"


def _parse_history_date(s):
    """Parse ISO 8601 date string with timezone. Returns None on failure."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _find_grabs_to_fail(records):
    """Find grabs whose corresponding download failed recently.

    Returns list of {grab_id, source_title, download_id, date} dicts,
    deduplicated by grab_id. Only includes failures within
    _BLOCKLIST_WINDOW_DAYS.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=_BLOCKLIST_WINDOW_DAYS)

    grabs_by_download_id = {}
    for r in records:
        if r.get("eventType") != "grabbed":
            continue
        did = (r.get("downloadId") or "").lower()
        if not did:
            continue
        grabs_by_download_id[did] = r

    seen_grab_ids = set()
    results = []

    for r in records:
        if r.get("eventType") != "downloadFailed":
            continue

        dt = _parse_history_date(r.get("date"))
        if dt and dt < cutoff:
            continue

        did = (r.get("downloadId") or "").lower()
        if not did:
            continue

        grab = grabs_by_download_id.get(did)
        if not grab:
            continue

        grab_id = grab.get("id")
        if not grab_id or grab_id in seen_grab_ids:
            continue
        seen_grab_ids.add(grab_id)

        results.append({
            "grab_id": grab_id,
            "source_title": grab.get("sourceTitle") or r.get("sourceTitle") or "Unknown",
            "download_id": did,
            "date": grab.get("date"),
        })

    return results


def _blocklist_releases_for(arr, item_id, dry_run=False):
    """Fail failed releases for one item via /history/failed/{grab_id}.

    Returns (blocklisted_count, error_or_None, payloads).
    payloads is always a list: empty on error, all candidates on dry_run,
    all candidates acted on (success or failure) on real runs. Each dict:
    {grab_id, source_title, download_id, date}.
    """
    records, err = _fetch_item_history(arr, item_id)
    if err:
        return 0, err, []

    grabs = _find_grabs_to_fail(records)
    if not grabs:
        return 0, None, []

    if dry_run:
        return 0, None, grabs

    api_url = arr["url"].rstrip("/")
    api_key = arr["api_key"]
    api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))

    success = 0
    errors = []
    for i, g in enumerate(grabs):
        # Pace POSTs so Prowlarr/indexers don't see a burst. Sleep between
        # calls, not after the last one. Unconditional so rate-limited
        # indexers still get breathing room even when a POST fails.
        if i > 0:
            time.sleep(_BLOCKLIST_POST_DELAY)
        try:
            req = Request(
                f"{api_url}/api/{api_ver}/history/failed/{g['grab_id']}",
                headers={"X-Api-Key": api_key},
                method="POST",
            )
            with _opener.open(req, timeout=15):
                pass
            success += 1
            logger.info(f"Failed+blocklisted '{g['source_title']}' for item {item_id} in {arr.get('name')}")
        except Exception as e:
            errors.append(f"{g['source_title']}: {e}")

    err_msg = None
    if errors:
        err_msg = "; ".join(errors[:3]) + ("..." if len(errors) > 3 else "")
    return success, err_msg, grabs
