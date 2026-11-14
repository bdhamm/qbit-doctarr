"""Config migration framework."""

import json
import logging
import os

logger = logging.getLogger(__name__)
CONFIG_PATH = "/config/config.json"
CURRENT_SCHEMA_VERSION = 7

_TASK_TIMEOUTS_V1 = {
    "bt_backup": 300, "unmanaged": 900, "stalled": 600, "extensions": 600,
    "quarantine": 600, "arr_health": 300, "missing": 0, "unmonitor": 0,
}

_NOTIFICATIONS_V2 = {
    "enabled": False,
    "email": {
        "enabled": False, "smtp_host": "", "smtp_port": 25, "tls_mode": "none",
        "username": "", "password": "", "from_addr": "qbit-doctarr@localhost", "to_addrs": ""
    }
}

_DIGEST_V4 = {
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

def _migrate_to_1(config):
    if not isinstance(config.get("task_timeouts"), dict):
        config["task_timeouts"] = dict(_TASK_TIMEOUTS_V1)
    else:
        for k, v in _TASK_TIMEOUTS_V1.items(): config["task_timeouts"].setdefault(k, v)

def _migrate_to_2(config):
    if not isinstance(config.get("notifications"), dict):
        config["notifications"] = json.loads(json.dumps(_NOTIFICATIONS_V2))
    else:
        existing = config["notifications"]
        for k, v in _NOTIFICATIONS_V2.items():
            if k == "email":
                if not isinstance(existing.get("email"), dict): existing["email"] = json.loads(json.dumps(_NOTIFICATIONS_V2["email"]))
                else:
                    for ek, ev in _NOTIFICATIONS_V2["email"].items(): existing["email"].setdefault(ek, ev)
            else: existing.setdefault(k, v)
    if isinstance(config.get("schedules"), dict):
        config["schedules"].setdefault("notify_time", 0.25)
        config["schedules"].setdefault("notify_unit", "hours")
    else: config["schedules"] = {"notify_time": 0.25, "notify_unit": "hours"}
    if isinstance(config.get("task_timeouts"), dict): config["task_timeouts"].setdefault("notify", 120)
    else: config["task_timeouts"] = {"notify": 120}

def _migrate_to_3(config):
    notif = config.get("notifications")
    if not isinstance(notif, dict):
        config["notifications"] = {"enabled": False, "muted_sources": [], "email": {}}
        return
    if not isinstance(notif.get("muted_sources"), list): notif["muted_sources"] = []
    if isinstance(notif.get("email"), dict) and "enabled" in notif["email"]: del notif["email"]["enabled"]

def _migrate_to_4(config):
    notif = config.get("notifications")
    if not isinstance(notif, dict): notif = config.setdefault("notifications", {})
    if not isinstance(notif.get("digest"), dict):
        notif["digest"] = json.loads(json.dumps(_DIGEST_V4))
    else:
        existing = notif["digest"]
        for k, v in _DIGEST_V4.items():
            if k == "sections":
                if not isinstance(existing.get("sections"), dict): existing["sections"] = json.loads(json.dumps(_DIGEST_V4["sections"]))
                else:
                    for sk, sv in _DIGEST_V4["sections"].items(): existing["sections"].setdefault(sk, sv)
            else: existing.setdefault(k, v)
    if isinstance(config.get("task_timeouts"), dict): config["task_timeouts"].setdefault("digest", 120)

def _migrate_to_5(config):
    notif = config.get("notifications")
    if not isinstance(notif, dict):
        notif = config.setdefault("notifications", {})
    muted = notif.get("muted_sources")
    if not isinstance(muted, list):
        muted = []
        notif["muted_sources"] = muted
    if "AllowedHostsCheck" not in muted:
        muted.append("AllowedHostsCheck")

def _migrate_to_6(config):
    if not isinstance(config.get("security"), dict):
        config["security"] = {
            "basic_auth_enabled": False,
            "basic_auth_username": "admin",
            "basic_auth_password": ""
        }
    else:
        existing = config["security"]
        existing.setdefault("basic_auth_enabled", False)
        existing.setdefault("basic_auth_username", "admin")
        existing.setdefault("basic_auth_password", "")

def _migrate_to_7(config):
    # Task 8: hourly metrics snapshot job.
    schedules = config.setdefault("schedules", {})
    schedules.setdefault("metrics_time", 1)
    schedules.setdefault("metrics_unit", "hours")
    timeouts = config.setdefault("task_timeouts", {})
    timeouts.setdefault("metrics", 60)

MIGRATIONS = {
    1: _migrate_to_1, 2: _migrate_to_2, 3: _migrate_to_3,
    4: _migrate_to_4, 5: _migrate_to_5, 6: _migrate_to_6,
    7: _migrate_to_7,
}

def run_migrations():
    if not os.path.exists(CONFIG_PATH): return
    try:
        with open(CONFIG_PATH, 'r') as f: config = json.load(f)
    except Exception as e:
        logger.error(f"Migration: failed to load config: {e}"); return
    try: current = int(config.get("schema_version", 0))
    except (ValueError, TypeError): current = 0
    if current >= CURRENT_SCHEMA_VERSION: return
    logger.info(f"Config migrations: v{current} -> v{CURRENT_SCHEMA_VERSION}")
    for target in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
        fn = MIGRATIONS.get(target)
        if not fn: continue
        try: fn(config)
        except Exception as e:
            logger.error(f"Migration to v{target} failed: {e}"); return
    config["schema_version"] = CURRENT_SCHEMA_VERSION
    try:
        with open(CONFIG_PATH, 'w') as f: json.dump(config, f, indent=4)
        logger.info(f"Config saved at schema v{CURRENT_SCHEMA_VERSION}")
    except Exception as e: logger.error(f"Migration: failed to save config: {e}")
