"""Shared config helpers for the routes package."""

import json
import os
from datetime import datetime, timezone

CONFIG_PATH = "/config/config.json"
DB_PATH = "/config/qbit-doctarr.db"

DEFAULT_CONFIG = {
    "schema_version": 7,
    "qbit": {"enabled": True, "url": "http://192.168.122.1:8080", "auth_method": "password", "username": "admin", "password": "", "api_key": ""},
    "thresholds": {
        "meta_time": 2, "meta_unit": "hours",
        "stalled_time": 48, "stalled_unit": "hours",
        "unmanaged_time": 168, "unmanaged_unit": "hours",
        "slow_speed_val": 10, "slow_speed_unit": "KiB",
        "max_percentage": 100, "target_100_seeds": False,
        "blocked_extensions": "exe,scr,bat,cmd,vbs,js,jse,wsf,wsh,msi,msp,com,pif,hta,cpl,msc,jar,py,ps1,reg,zipx,arj,iso,img,vhd,vhdx",
        "approved_extensions": "mkv,mp4,avi,mov,srt,sub,ass,mp3,flac,m4a,epub,pdf,azw3",
        "missing_polite_mode": True,
        "missing_batch_size": 3,
        "missing_batch_mode": "per_arr",
        "missing_cooldown_hours": 24,
        "missing_max_retries": 5,
        "quarantine_retention_days": 7
    },
    "global_dry_run": False,
    "history_retention": 100,
    "log_level": "INFO",
    "log_to_file": False,
    "unmonitor_mode": "items",
    "unmonitor_ignore_specials": True,
    "unmonitor_force_refresh": True,
    "unmonitor_refresh_timeout_sec": 600,
    "schedules_enabled": True,
    "quarantine_limit_enabled": True,
    "quarantine_limit": 100,
    "dashboard_hidden_cards": [],
    "security": {
        "basic_auth_enabled": False,
        "basic_auth_username": "admin",
        "basic_auth_password": ""
    },
    "paths": {"external_torrent_dirs": []},
    "schedules": {
        "bt_backup_time": 24, "bt_backup_unit": "hours",
        "stalled_time": 1, "stalled_unit": "hours",
        "unmanaged_time": 24, "unmanaged_unit": "hours",
        "extensions_time": 0.5, "extensions_unit": "hours",
        "missing_time": 6, "missing_unit": "hours",
        "quarantine_time": 24, "quarantine_unit": "hours",
        "unmonitor_time": 24, "unmonitor_unit": "hours",
        "arr_health_time": 6, "arr_health_unit": "hours",
        "notify_time": 0.25, "notify_unit": "hours",
        "metrics_time": 1, "metrics_unit": "hours"
    },
    "task_timeouts": {
        "bt_backup": 300, "unmanaged": 900, "stalled": 600, "extensions": 600,
        "quarantine": 600, "arr_health": 300, "missing": 0, "unmonitor": 0,
        "notify": 120, "digest": 120, "metrics": 60
    },
    "notifications": {
        "enabled": False,
        "muted_sources": ["AllowedHostsCheck"],
        "email": {
            "smtp_host": "", "smtp_port": 25, "tls_mode": "none",
            "username": "", "password": "", "from_addr": "qbit-doctarr@localhost", "to_addrs": ""
        },
        "digest": {
            "enabled": False,
            "frequency": "weekly",
            "hour": 8,
            "day_of_week": 0,
            "day_of_month": 1,
            "sections": {
                "task_activity": True,
                "health_changes": True,
                "current_snapshot": True,
                "notable_events": True
            }
        }
    },
    "arrs": []
}

def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w') as f: json.dump(DEFAULT_CONFIG, f, indent=4)
    with open(CONFIG_PATH, 'r') as f: return json.load(f)

def _local_time(utc_str):
    if not utc_str: return utc_str
    s = str(utc_str)
    if s.startswith("1970-01-01"): return s
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str
