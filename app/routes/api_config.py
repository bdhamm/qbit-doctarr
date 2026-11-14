"""Config save + connectivity test endpoints."""

import json
from urllib.request import Request, build_opener

from flask import request, jsonify

from ..scheduler import update_schedules
from ..core.tasks._shared.qbit import QBittorrentAPI
from ..core.tasks._shared.config import resolve_api_version
from ..core.tasks.notify import suppress_historical_pending, send_test_email
from ._shared import CONFIG_PATH, load_config
from . import bp

@bp.route('/api/config', methods=['POST'])
def save_config():
    new_config = request.json
    current_config = load_config()
    old_notif = current_config.get("notifications") or {}
    old_enabled = bool(old_notif.get("enabled", False))
    old_muted = set(str(s).strip() for s in (old_notif.get("muted_sources") or []) if str(s).strip())

    for key, value in new_config.items():
        if isinstance(value, dict) and key in current_config: current_config[key].update(value)
        else: current_config[key] = value

    with open(CONFIG_PATH, 'w') as f: json.dump(current_config, f, indent=4)

    new_notif = current_config.get("notifications") or {}
    new_enabled = bool(new_notif.get("enabled", False))
    new_muted = set(str(s).strip() for s in (new_notif.get("muted_sources") or []) if str(s).strip())

    suppressed = 0
    if new_enabled and not old_enabled:
        suppressed = suppress_historical_pending(sources=None)
    elif new_enabled and old_enabled:
        unmuted = old_muted - new_muted
        if unmuted: suppressed = suppress_historical_pending(sources=sorted(unmuted))

    update_schedules()
    return jsonify({"status": "success", "suppressed": suppressed})

@bp.route('/api/test-notify', methods=['POST'])
def test_notify():
    config = load_config()
    try:
        send_test_email(config)
        return jsonify({"status": "success", "message": "Test email sent successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/api/test-qbit', methods=['POST'])
def test_qbit():
    data = request.json
    url = data.get("url", "").strip()
    if not url: return jsonify({"status": "error", "message": "qBittorrent URL is required."}), 400
    temp_config = {"qbit": {"url": url, "auth_method": data.get("auth_method", "password"), "username": data.get("username", ""), "password": data.get("password", ""), "api_key": data.get("api_key", "")}}
    try:
        api = QBittorrentAPI(temp_config)
        torrents = api.get_torrents()
        return jsonify({"status": "success", "message": f"Successfully connected! Found {len(torrents)} torrents."})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 400

@bp.route('/api/test-arr', methods=['POST'])
def test_arr():
    data = request.json
    arr_type = data.get("type", "radarr").lower()
    url = data.get("url", "").rstrip("/")
    api_key = data.get("api_key", "")
    api_ver = resolve_api_version(arr_type, data.get("api_version", "auto"))
    if not url or not api_key: return jsonify({"status": "error", "message": "URL and API Key are required."}), 400
    test_url = f"{url}/api/{api_ver}/system/status"
    try:
        req = Request(test_url, headers={"X-Api-Key": api_key})
        with build_opener().open(req, timeout=10) as resp:
            status_data = json.loads(resp.read())
            version = status_data.get("version", "unknown")
            return jsonify({"status": "success", "message": f"Connected successfully! {arr_type.capitalize()} version {version}"})
    except Exception as e: return jsonify({"status": "error", "message": f"Connection failed. Check URL/API Key. Error: {e}"}), 400
