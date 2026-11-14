import json
import os
from datetime import timedelta

CONFIG_PATH = "/config/config.json"
DB_PATH = "/config/qbit-doctarr.db"
BT_BACKUP_PATH = "/qbittorrent_data/BT_backup"
QUARANTINE_PATH = "/downloads/quarantine"
MISSING_PAGE_SIZE = 100

_config_cache = {"mtime": 0, "data": None}


def resolve_api_version(arr_type: str, configured_version: str) -> str:
    if configured_version and configured_version.lower() != "auto": return configured_version
    if arr_type in ["lidarr", "readarr", "chaptarr"]: return "v1"
    return "v3"


def calc_delta(val, unit):
    if unit == "minutes": return timedelta(minutes=float(val))
    return timedelta(hours=float(val))


def _arr_family(arr):
    t = arr.get("type", "radarr").lower()
    if t == "whisparr":
        version = (arr.get("whisparr_version") or "v3").lower()
        return "sonarr" if version == "v2" else "radarr"
    return t


def load_config():
    try:
        mtime = os.stat(CONFIG_PATH).st_mtime_ns
        if _config_cache["data"] is not None and _config_cache["mtime"] == mtime:
            return _config_cache["data"]
        with open(CONFIG_PATH, 'r') as f:
            data = json.load(f)
        _config_cache["data"] = data
        _config_cache["mtime"] = mtime
        return data
    except Exception:
        with open(CONFIG_PATH, 'r') as f: return json.load(f)