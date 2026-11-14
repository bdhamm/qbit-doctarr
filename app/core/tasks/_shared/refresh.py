import json
import time
from urllib.request import Request, build_opener
from .config import _arr_family, resolve_api_version
from .logging import logger

_opener = build_opener()


def _refresh_command_for_family(family):
    return {
        "radarr": "RefreshMovie",
        "sonarr": "RescanSeries",
        "lidarr": "RefreshArtist",
        "readarr": "RefreshAuthor",
        "chaptarr": "RefreshAuthor",
    }.get(family)


def _refresh_single_arr(arr, timeout_sec=600):
    try:
        api_url = arr["url"].rstrip("/")
        api_key = arr["api_key"]
        api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
        family = _arr_family(arr)
        cmd_name = _refresh_command_for_family(family)
        if not cmd_name:
            return False, f"No refresh command for family '{family}'"
        req = Request(
            f"{api_url}/api/{api_ver}/command",
            data=json.dumps({"name": cmd_name}).encode(),
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            method="POST"
        )
        with _opener.open(req, timeout=15) as resp:
            cmd = json.loads(resp.read())
        cmd_id = cmd.get("id")
        if not cmd_id:
            return False, "Refresh command did not return an id"
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(5)
            try:
                status_req = Request(f"{api_url}/api/{api_ver}/command/{cmd_id}", headers={"X-Api-Key": api_key})
                with _opener.open(status_req, timeout=10) as resp:
                    status = json.loads(resp.read())
                s = str(status.get("status", "")).lower()
                if s == "completed":
                    r = str(status.get("result", "")).lower()
                    if r in ("unsuccessful", "failed", "aborted", "cancelled"):
                        return False, f"completed with result '{r}'"
                    return True, "completed"
                if s in ("failed", "aborted", "cancelled", "orphaned"):
                    return False, f"refresh ended with status '{s}'"
            except Exception as e:
                logger.warning(f"Error polling refresh status for {arr.get('name')}: {e}")
        return False, f"timed out after {timeout_sec}s"
    except Exception as e:
        return False, f"error: {e}"


def _refresh_arrs_sequential(arrs, timeout_sec=600):
    results = {}
    if not arrs:
        return results

    def sort_key(arr):
        family = _arr_family(arr)
        is_slow = family in ("sonarr", "lidarr")
        return (is_slow, arr.get("name", ""))

    ordered = sorted(arrs, key=sort_key)
    total = len(ordered)

    for i, arr in enumerate(ordered, 1):
        name = arr.get("name", "Unknown")
        family = _arr_family(arr)
        logger.info(f"Refreshing {name} ({family}) — {i}/{total}...")
        try:
            ok, msg = _refresh_single_arr(arr, timeout_sec)
        except Exception as e:
            ok, msg = False, f"unexpected error: {e}"
        results[name] = (ok, msg)
        if i < total:
            time.sleep(2)

    return results