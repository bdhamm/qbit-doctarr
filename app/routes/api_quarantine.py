"""Quarantine folder browsing and manual deletion."""

from pathlib import Path

from flask import request, jsonify

from ..core.tasks._shared.config import QUARANTINE_PATH
from ._shared import load_config
from . import bp


@bp.route('/api/quarantine/list')
def list_quarantine():
    config = load_config()
    search = request.args.get('search', '').lower()
    q_path = Path(QUARANTINE_PATH)
    if not q_path.exists(): return jsonify({"files": [], "total": 0})
    all_files = [f.name for f in q_path.iterdir() if f.is_file()]
    filtered = [f for f in all_files if search in f.lower()] if search else all_files
    total = len(filtered)
    limit_enabled = config.get("quarantine_limit_enabled", True)
    limit_val = int(config.get("quarantine_limit", 100))
    results = sorted(filtered)[:limit_val] if limit_enabled and limit_val > 0 else sorted(filtered)
    return jsonify({"files": results, "total": total})


@bp.route('/api/quarantine/delete', methods=['POST'])
def delete_quarantine():
    filenames = request.json.get("files", [])
    q_path = Path(QUARANTINE_PATH)
    deleted = 0
    for f in filenames:
        safe_name = Path(f).name
        target = q_path / safe_name
        if target.exists() and target.is_file():
            try:
                target.unlink()
                deleted += 1
            except Exception: pass
    return jsonify({"status": "success", "message": f"Deleted {deleted} files."})