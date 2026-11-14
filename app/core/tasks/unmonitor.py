import json
from urllib.request import Request, build_opener

from ._shared.config import _arr_family, load_config, resolve_api_version
from ._shared.refresh import _refresh_arrs_sequential
from ._shared.logging import logger, _log_full_and_truncated

_opener = build_opener()


def _is_deceased(arr_item):
    for meta_key in ("artistMetadata", "authorMetadata"):
        metadata = arr_item.get(meta_key) or {}
        if metadata.get("deceased"):
            return True
    return bool(arr_item.get("deceased", False))


def _album_is_complete(album):
    stats = album.get("statistics") or {}
    total = int(stats.get("totalTrackCount", 0) or 0)
    have = int(stats.get("trackFileCount", 0) or 0)
    return total > 0 and have >= total


def _book_is_complete(book):
    stats = book.get("statistics") or {}
    have = int(stats.get("bookFileCount", 0) or 0)
    return have > 0


def _unmonitor_radarr(api_url, api_key, api_ver, mode, is_dry_run, arr_name, audit_list):
    req = Request(f"{api_url}/api/{api_ver}/movie", headers={"X-Api-Key": api_key})
    with _opener.open(req, timeout=30) as resp:
        movies = json.loads(resp.read())
    to_unmonitor = [m for m in movies if m.get("monitored") and m.get("hasFile")]
    if not to_unmonitor:
        return 0, []
    ids = [m["id"] for m in to_unmonitor]
    titles = [m.get("title", "Unknown") for m in to_unmonitor]
    if is_dry_run:
        audit_list.append(f"[{arr_name}] [DRY RUN] Would unmonitor {len(ids)} movie(s).")
        for t in titles:
            audit_list.append(f"[{arr_name}] [DRY RUN] Would unmonitor movie: {t}")
        return len(ids), titles
    chunk_size = 100
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i:i+chunk_size]
        payload = {"movieIds": chunk, "monitored": False}
        req = Request(
            f"{api_url}/api/{api_ver}/movie/editor",
            data=json.dumps(payload).encode(),
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            method="PUT"
        )
        with _opener.open(req, timeout=30) as resp:
            if resp.status not in (200, 202):
                raise Exception(f"HTTP {resp.status}")
    audit_list.append(f"[{arr_name}] Unmonitored {len(ids)} movie(s).")
    for t in titles:
        audit_list.append(f"[{arr_name}] Unmonitored movie: {t}")
    return len(ids), titles


def _unmonitor_sonarr(api_url, api_key, api_ver, mode, ignore_specials, is_dry_run, arr_name, audit_list):
    req = Request(f"{api_url}/api/{api_ver}/series", headers={"X-Api-Key": api_key})
    with _opener.open(req, timeout=30) as resp:
        series_list = json.loads(resp.read())
    
    # N+1 Fix: Fetch all episodes in bulk (with pagination to prevent 400 error)
    episodes_by_series = {}
    try:
        ep_req = Request(f"{api_url}/api/{api_ver}/episode?page=1&pageSize=100000", headers={"X-Api-Key": api_key})
        with _opener.open(ep_req, timeout=60) as resp:
            all_episodes = json.loads(resp.read())
            for ep in all_episodes:
                s_id = ep.get("seriesId")
                if s_id: episodes_by_series.setdefault(s_id, []).append(ep)
    except Exception as e:
        logger.warning(f"[{arr_name}] Bulk episode fetch failed, falling back to per-series: {e}")

    total_count = 0
    all_titles = []
    for series in series_list:
        series_id = series.get("id")
        if not series_id: continue
        if not series.get("monitored", True):
            continue
        series_title = series.get("title") or f"Series {series_id}"
        
        episodes = episodes_by_series.get(series_id)
        if episodes is None:
            # Fallback if bulk fetch failed
            ep_req = Request(f"{api_url}/api/{api_ver}/episode?seriesId={series_id}", headers={"X-Api-Key": api_key})
            try:
                with _opener.open(ep_req, timeout=30) as resp:
                    episodes = json.loads(resp.read())
            except Exception:
                episodes = []

        if not episodes: continue
        seasons = {}
        for ep in episodes:
            s_num = ep.get("seasonNumber")
            if s_num is None: continue
            if ignore_specials and s_num == 0: continue
            seasons.setdefault(s_num, []).append(ep)
        if not seasons: continue
        all_eps = [ep for eps in seasons.values() for ep in eps]
        series_complete = bool(all_eps) and all(bool(ep.get("hasFile")) for ep in all_eps)
        series_ended = bool(series.get("ended", False)) or str(series.get("status", "")).lower() in ("ended", "deleted")

        if mode == "items_seasons_parents" and series_complete and series_ended:
            monitored_ep_ids_in_series = [ep["id"] for ep in episodes if ep.get("monitored")]
            if is_dry_run:
                audit_list.append(
                    f"[{arr_name}] [DRY RUN] Would unmonitor series (ended+complete) + "
                    f"{len(monitored_ep_ids_in_series)} episode(s): {series_title}"
                )
                total_count += 1
                all_titles.append(series_title)
                continue
            try:
                payload = {"seriesIds": [series_id], "monitored": False}
                req = Request(
                    f"{api_url}/api/{api_ver}/series/editor",
                    data=json.dumps(payload).encode(),
                    headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                    method="PUT"
                )
                with _opener.open(req, timeout=30) as resp:
                    if resp.status not in (200, 202):
                        audit_list.append(f"[{arr_name}] ERROR unmonitoring series '{series_title}': HTTP {resp.status}")
                        continue
                if monitored_ep_ids_in_series:
                    chunk_size = 100
                    for i in range(0, len(monitored_ep_ids_in_series), chunk_size):
                        chunk = monitored_ep_ids_in_series[i:i+chunk_size]
                        ep_payload = {"episodeIds": chunk, "monitored": False}
                        ep_req2 = Request(
                            f"{api_url}/api/{api_ver}/episode/monitor",
                            data=json.dumps(ep_payload).encode(),
                            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                            method="PUT"
                        )
                        with _opener.open(ep_req2, timeout=30) as resp2:
                            if resp2.status not in (200, 202):
                                logger.warning(f"[{arr_name}] Failed to unmonitor episodes of '{series_title}': HTTP {resp2.status}")
                season_updates = [{"seasonNumber": s, "monitored": False} for s in seasons.keys()]
                sp_payload = {"series": [{"id": series_id, "seasons": season_updates}]}
                sp_req = Request(
                    f"{api_url}/api/{api_ver}/seasonpass",
                    data=json.dumps(sp_payload).encode(),
                    headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                    method="POST"
                )
                with _opener.open(sp_req, timeout=30) as resp3:
                    if resp3.status not in (200, 202):
                        logger.warning(f"[{arr_name}] Failed to update season monitored flags for '{series_title}': HTTP {resp3.status}")
                audit_list.append(
                    f"[{arr_name}] Unmonitored series (ended+complete) + "
                    f"{len(monitored_ep_ids_in_series)} episode(s): {series_title}"
                )
                total_count += 1
                all_titles.append(series_title)
            except Exception as e:
                audit_list.append(f"[{arr_name}] ERROR unmonitoring series '{series_title}': {e}")
            continue

        season_flags = {}
        for s in (series.get("seasons") or []):
            sn = s.get("seasonNumber")
            if sn is not None:
                season_flags[sn] = bool(s.get("monitored", True))

        episode_ids = []
        episode_labels = []
        seasons_with_episode_actions = set()
        seasons_needing_flag_sync = set()

        for s_num, eps in seasons.items():
            monitored_eps = [ep for ep in eps if ep.get("monitored")]
            all_have_files = all(bool(ep.get("hasFile")) for ep in eps)

            if not monitored_eps:
                if mode in ("items_seasons", "items_seasons_parents") and all_have_files:
                    if season_flags.get(s_num, True):
                        seasons_needing_flag_sync.add(s_num)
                continue

            complete_season = all(bool(ep.get("hasFile")) for ep in monitored_eps)
            if mode in ("items_seasons", "items_seasons_parents") and complete_season:
                for ep in monitored_eps:
                    episode_ids.append(ep["id"])
                episode_labels.append(f"{series_title} S{int(s_num):02d} (whole season, {len(monitored_eps)} eps)")
                seasons_with_episode_actions.add(s_num)
            else:
                for ep in monitored_eps:
                    if not bool(ep.get("hasFile")): continue
                    episode_ids.append(ep["id"])
                    ep_num = ep.get("episodeNumber")
                    if isinstance(ep_num, int):
                        episode_labels.append(f"{series_title} S{int(s_num):02d}E{ep_num:02d}")
                    else:
                        episode_labels.append(f"{series_title} S{int(s_num):02d}E{ep_num}")

        if not episode_ids and not seasons_needing_flag_sync:
            continue

        if is_dry_run:
            if episode_ids:
                audit_list.append(f"[{arr_name}] [DRY RUN] Would unmonitor {len(episode_ids)} item(s) in '{series_title}'")
                total_count += len(episode_ids)
                all_titles.extend(episode_labels)
            if seasons_needing_flag_sync:
                sn_list = sorted(seasons_needing_flag_sync)
                sn_labels = ", ".join(f"S{int(s):02d}" for s in sn_list)
                audit_list.append(
                    f"[{arr_name}] [DRY RUN] Would sync season flag(s) to unmonitored in "
                    f"'{series_title}': {sn_labels}"
                )
            continue

        try:
            if episode_ids:
                chunk_size = 100
                for i in range(0, len(episode_ids), chunk_size):
                    chunk = episode_ids[i:i+chunk_size]
                    payload = {"episodeIds": chunk, "monitored": False}
                    req = Request(
                        f"{api_url}/api/{api_ver}/episode/monitor",
                        data=json.dumps(payload).encode(),
                        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                        method="PUT"
                    )
                    with _opener.open(req, timeout=30) as resp:
                        if resp.status not in (200, 202):
                            raise Exception(f"HTTP {resp.status}")
            all_seasons_to_flag = seasons_with_episode_actions | seasons_needing_flag_sync
            if all_seasons_to_flag:
                season_updates = [{"seasonNumber": s, "monitored": False} for s in all_seasons_to_flag]
                sp_payload = {"series": [{"id": series_id, "seasons": season_updates}]}
                sp_req = Request(
                    f"{api_url}/api/{api_ver}/seasonpass",
                    data=json.dumps(sp_payload).encode(),
                    headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                    method="POST"
                )
                with _opener.open(sp_req, timeout=30) as resp:
                    if resp.status not in (200, 202):
                        logger.warning(f"[{arr_name}] Failed to update season monitored flags for '{series_title}': HTTP {resp.status}")
            if episode_ids:
                audit_list.append(f"[{arr_name}] Unmonitored {len(episode_ids)} item(s) in '{series_title}'")
                total_count += len(episode_ids)
                all_titles.extend(episode_labels)
            if seasons_needing_flag_sync:
                sn_list = sorted(seasons_needing_flag_sync)
                sn_labels = ", ".join(f"S{int(s):02d}" for s in sn_list)
                audit_list.append(
                    f"[{arr_name}] Synced season flag(s) to unmonitored in "
                    f"'{series_title}': {sn_labels}"
                )
        except Exception as e:
            audit_list.append(f"[{arr_name}] ERROR unmonitoring items in '{series_title}': {e}")
    return total_count, all_titles


def _unmonitor_lidarr(api_url, api_key, api_ver, mode, is_dry_run, arr_name, audit_list):
    req = Request(f"{api_url}/api/{api_ver}/artist", headers={"X-Api-Key": api_key})
    with _opener.open(req, timeout=30) as resp:
        artists = json.loads(resp.read())

    albums_by_artist = {}
    try:
        alb_req = Request(f"{api_url}/api/{api_ver}/album", headers={"X-Api-Key": api_key})
        with _opener.open(alb_req, timeout=60) as resp:
            all_albums = json.loads(resp.read())
            for alb in all_albums:
                a_id = alb.get("artistId")
                if a_id: albums_by_artist.setdefault(a_id, []).append(alb)
    except Exception as e:
        logger.warning(f"[{arr_name}] Bulk album fetch failed: {e}")

    total_count = 0
    all_titles = []
    for artist in artists:
        artist_id = artist.get("id")
        if not artist_id: continue
        if not artist.get("monitored", True):
            continue
        artist_name = artist.get("artistName") or f"Artist {artist_id}"
        deceased = _is_deceased(artist)
        
        albums = albums_by_artist.get(artist_id)
        if albums is None:
            alb_req = Request(f"{api_url}/api/{api_ver}/album?artistId={artist_id}", headers={"X-Api-Key": api_key})
            try:
                with _opener.open(alb_req, timeout=30) as resp:
                    albums = json.loads(resp.read())
            except Exception:
                albums = []

        if not albums: continue
        monitored_albums = [a for a in albums if a.get("monitored")]
        if not monitored_albums: continue
        artist_complete = all(_album_is_complete(a) for a in monitored_albums)

        if mode == "items_seasons_parents" and artist_complete and deceased:
            monitored_album_ids_in_artist = [a["id"] for a in albums if a.get("monitored")]
            if is_dry_run:
                audit_list.append(
                    f"[{arr_name}] [DRY RUN] Would unmonitor artist (deceased+complete) + "
                    f"{len(monitored_album_ids_in_artist)} album(s): {artist_name}"
                )
                total_count += 1
                all_titles.append(artist_name)
                continue
            try:
                payload = {"artistIds": [artist_id], "monitored": False}
                req = Request(
                    f"{api_url}/api/{api_ver}/artist/editor",
                    data=json.dumps(payload).encode(),
                    headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                    method="PUT"
                )
                with _opener.open(req, timeout=30) as resp:
                    if resp.status not in (200, 202):
                        audit_list.append(f"[{arr_name}] ERROR unmonitoring artist '{artist_name}': HTTP {resp.status}")
                        continue
                if monitored_album_ids_in_artist:
                    chunk_size = 100
                    for i in range(0, len(monitored_album_ids_in_artist), chunk_size):
                        chunk = monitored_album_ids_in_artist[i:i+chunk_size]
                        alb_payload = {"albumIds": chunk, "monitored": False}
                        alb_req2 = Request(
                            f"{api_url}/api/{api_ver}/album/monitor",
                            data=json.dumps(alb_payload).encode(),
                            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                            method="PUT"
                        )
                        with _opener.open(alb_req2, timeout=30) as resp2:
                            if resp2.status not in (200, 202):
                                logger.warning(f"[{arr_name}] Failed to unmonitor albums of '{artist_name}': HTTP {resp2.status}")
                audit_list.append(
                    f"[{arr_name}] Unmonitored artist (deceased+complete) + "
                    f"{len(monitored_album_ids_in_artist)} album(s): {artist_name}"
                )
                total_count += 1
                all_titles.append(artist_name)
            except Exception as e:
                audit_list.append(f"[{arr_name}] ERROR unmonitoring artist '{artist_name}': {e}")
            continue

        albums_to_unmonitor = [a for a in monitored_albums if _album_is_complete(a)]
        if not albums_to_unmonitor: continue
        album_ids = [a["id"] for a in albums_to_unmonitor]
        album_labels = [f"{artist_name} - {a.get('title', 'Unknown')}" for a in albums_to_unmonitor]
        if is_dry_run:
            audit_list.append(f"[{arr_name}] [DRY RUN] Would unmonitor {len(album_ids)} album(s) from '{artist_name}'")
            total_count += len(album_ids)
            all_titles.extend(album_labels)
            continue
        try:
            chunk_size = 100
            for i in range(0, len(album_ids), chunk_size):
                chunk = album_ids[i:i+chunk_size]
                payload = {"albumIds": chunk, "monitored": False}
                req = Request(
                    f"{api_url}/api/{api_ver}/album/monitor",
                    data=json.dumps(payload).encode(),
                    headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                    method="PUT"
                )
                with _opener.open(req, timeout=30) as resp:
                    if resp.status not in (200, 202):
                        raise Exception(f"HTTP {resp.status}")
            audit_list.append(f"[{arr_name}] Unmonitored {len(album_ids)} album(s) from '{artist_name}'")
            total_count += len(album_ids)
            all_titles.extend(album_labels)
        except Exception as e:
            audit_list.append(f"[{arr_name}] ERROR unmonitoring albums from '{artist_name}': {e}")
    return total_count, all_titles


def _unmonitor_readarr(api_url, api_key, api_ver, mode, is_dry_run, arr_name, audit_list):
    req = Request(f"{api_url}/api/{api_ver}/author", headers={"X-Api-Key": api_key})
    with _opener.open(req, timeout=30) as resp:
        authors = json.loads(resp.read())

    books_by_author = {}
    try:
        bk_req = Request(f"{api_url}/api/{api_ver}/book", headers={"X-Api-Key": api_key})
        with _opener.open(bk_req, timeout=60) as resp:
            all_books = json.loads(resp.read())
            for bk in all_books:
                a_id = bk.get("authorId")
                if a_id: books_by_author.setdefault(a_id, []).append(bk)
    except Exception as e:
        logger.warning(f"[{arr_name}] Bulk book fetch failed: {e}")

    total_count = 0
    all_titles = []
    for author in authors:
        author_id = author.get("id")
        if not author_id: continue
        if not author.get("monitored", True):
            continue
        author_name = author.get("authorName") or f"Author {author_id}"
        deceased = _is_deceased(author)
        
        books = books_by_author.get(author_id)
        if books is None:
            bk_req = Request(f"{api_url}/api/{api_ver}/book?authorId={author_id}", headers={"X-Api-Key": api_key})
            try:
                with _opener.open(bk_req, timeout=30) as resp:
                    books = json.loads(resp.read())
            except Exception:
                books = []

        if not books: continue
        monitored_books = [b for b in books if b.get("monitored")]
        if not monitored_books: continue
        author_complete = all(_book_is_complete(b) for b in monitored_books)

        if mode == "items_seasons_parents" and author_complete and deceased:
            monitored_book_ids_in_author = [b["id"] for b in books if b.get("monitored")]
            if is_dry_run:
                audit_list.append(
                    f"[{arr_name}] [DRY RUN] Would unmonitor author (deceased+complete) + "
                    f"{len(monitored_book_ids_in_author)} book(s): {author_name}"
                )
                total_count += 1
                all_titles.append(author_name)
                continue
            try:
                payload = {"authorIds": [author_id], "monitored": False}
                req = Request(
                    f"{api_url}/api/{api_ver}/author/editor",
                    data=json.dumps(payload).encode(),
                    headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                    method="PUT"
                )
                with _opener.open(req, timeout=30) as resp:
                    if resp.status not in (200, 202):
                        audit_list.append(f"[{arr_name}] ERROR unmonitoring author '{author_name}': HTTP {resp.status}")
                        continue
                if monitored_book_ids_in_author:
                    chunk_size = 100
                    for i in range(0, len(monitored_book_ids_in_author), chunk_size):
                        chunk = monitored_book_ids_in_author[i:i+chunk_size]
                        bk_payload = {"bookIds": chunk, "monitored": False}
                        bk_req2 = Request(
                            f"{api_url}/api/{api_ver}/book/monitor",
                            data=json.dumps(bk_payload).encode(),
                            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                            method="PUT"
                        )
                        with _opener.open(bk_req2, timeout=30) as resp2:
                            if resp2.status not in (200, 202):
                                logger.warning(f"[{arr_name}] Failed to unmonitor books of '{author_name}': HTTP {resp2.status}")
                audit_list.append(
                    f"[{arr_name}] Unmonitored author (deceased+complete) + "
                    f"{len(monitored_book_ids_in_author)} book(s): {author_name}"
                )
                total_count += 1
                all_titles.append(author_name)
            except Exception as e:
                audit_list.append(f"[{arr_name}] ERROR unmonitoring author '{author_name}': {e}")
            continue

        books_to_unmonitor = [b for b in monitored_books if _book_is_complete(b)]
        if not books_to_unmonitor: continue
        book_ids = [b["id"] for b in books_to_unmonitor]
        book_labels = [f"{author_name} - {b.get('title', 'Unknown')}" for b in books_to_unmonitor]
        if is_dry_run:
            audit_list.append(f"[{arr_name}] [DRY RUN] Would unmonitor {len(book_ids)} book(s) from '{author_name}'")
            total_count += len(book_ids)
            all_titles.extend(book_labels)
            continue
        try:
            chunk_size = 100
            for i in range(0, len(book_ids), chunk_size):
                chunk = book_ids[i:i+chunk_size]
                payload = {"bookIds": chunk, "monitored": False}
                req = Request(
                    f"{api_url}/api/{api_ver}/book/monitor",
                    data=json.dumps(payload).encode(),
                    headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                    method="PUT"
                )
                with _opener.open(req, timeout=30) as resp:
                    if resp.status not in (200, 202):
                        raise Exception(f"HTTP {resp.status}")
            audit_list.append(f"[{arr_name}] Unmonitored {len(book_ids)} book(s) from '{author_name}'")
            total_count += len(book_ids)
            all_titles.extend(book_labels)
        except Exception as e:
            audit_list.append(f"[{arr_name}] ERROR unmonitoring books from '{author_name}': {e}")
    return total_count, all_titles


def task_unmonitor_items(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    logger.info(f"Starting Unmonitor Items (Dry Run: {is_dry_run})...")
    mode = config.get("unmonitor_mode", "items")
    ignore_specials = bool(config.get("unmonitor_ignore_specials", True))
    force_refresh = bool(config.get("unmonitor_force_refresh", True))
    refresh_timeout = int(config.get("unmonitor_refresh_timeout_sec", 600))
    logger.info(f"Unmonitor mode: {mode} | Ignore specials: {ignore_specials} | Force refresh: {force_refresh} (timeout {refresh_timeout}s)")
    total_unmonitored = 0
    audit_list = []
    actioned_names = []

    eligible_arrs = []
    for arr in config.get("arrs", []):
        if not arr.get("enabled", True):
            continue
        if not arr.get("unmonitor_has_file", False):
            audit_list.append(f"[{arr.get('name', 'Unknown')}] Skipped: 'Unmonitor Downloaded' is disabled for this *arr in Settings.")
            logger.info(f"Skipping {arr.get('name', 'Unknown')} for unmonitor — 'Unmonitor Downloaded' is disabled.")
            continue
        eligible_arrs.append(arr)

    refresh_results = {}
    if force_refresh and not is_dry_run and eligible_arrs:
        logger.info(f"Force-refreshing {len(eligible_arrs)} *arr(s) before unmonitor (sequential, {refresh_timeout}s timeout each)...")
        audit_list.append(f"Refreshing {len(eligible_arrs)} *arr(s) before evaluation (sequential, {refresh_timeout}s timeout each)...")
        refresh_results = _refresh_arrs_sequential(eligible_arrs, refresh_timeout)
        for name, (ok, msg) in sorted(refresh_results.items()):
            if ok:
                logger.info(f"Refresh completed: {name}")
                audit_list.append(f"[{name}] Refresh completed.")
            else:
                logger.warning(f"Refresh failed or timed out for {name}: {msg} — skipping this *arr this cycle.")
                audit_list.append(f"[{name}] Refresh failed or timed out ({msg}) — skipping this *arr this cycle.")
    elif force_refresh and is_dry_run:
        audit_list.append("[DRY RUN] Would force-refresh all eligible *arrs before evaluation (skipped in dry run).")

    for arr in eligible_arrs:
        arr_name = arr.get("name", "Unknown *Arr")
        if force_refresh and not is_dry_run:
            ok, msg = refresh_results.get(arr_name, (False, "refresh not attempted"))
            if not ok:
                continue
        api_url = arr["url"].rstrip("/")
        api_key = arr["api_key"]
        api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
        family = _arr_family(arr)
        try:
            if family == "radarr":
                count, titles = _unmonitor_radarr(api_url, api_key, api_ver, mode, is_dry_run, arr_name, audit_list)
            elif family == "sonarr":
                count, titles = _unmonitor_sonarr(api_url, api_key, api_ver, mode, ignore_specials, is_dry_run, arr_name, audit_list)
            elif family == "lidarr":
                count, titles = _unmonitor_lidarr(api_url, api_key, api_ver, mode, is_dry_run, arr_name, audit_list)
            elif family in ("readarr", "chaptarr"):
                count, titles = _unmonitor_readarr(api_url, api_key, api_ver, mode, is_dry_run, arr_name, audit_list)
            else:
                continue
            total_unmonitored += count
            actioned_names.extend(titles)
        except Exception as e:
            logger.error(f"Failed to unmonitor items for {arr_name}: {e}")
            audit_list.append(f"[{arr_name}] ERROR unmonitoring: {e}")

    if mode == "items":
        action_str = f"Found {total_unmonitored} item(s) to unmonitor" if is_dry_run else f"Unmonitored {total_unmonitored} item(s)"
    elif mode == "items_seasons":
        action_str = f"Found {total_unmonitored} item(s)/season(s) to unmonitor" if is_dry_run else f"Unmonitored {total_unmonitored} item(s)/season(s)"
    else:
        action_str = f"Found {total_unmonitored} item(s)/season(s)/parent(s) to unmonitor" if is_dry_run else f"Unmonitored {total_unmonitored} item(s)/season(s)/parent(s)"

    refresh_skipped_arrs = [name for name, (ok, _) in refresh_results.items() if not ok]
    refresh_skip_suffix = f" — refresh failed for: {', '.join(refresh_skipped_arrs)}" if refresh_skipped_arrs else ""

    details = _log_full_and_truncated(
        "Unmonitor Items", "Success", action_str, actioned_names,
        is_dry_run=is_dry_run, extra_suffix=refresh_skip_suffix,
    )
    return total_unmonitored, details, audit_list