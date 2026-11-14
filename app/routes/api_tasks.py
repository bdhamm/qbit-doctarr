"""Manual task trigger endpoint. Dispatches to task_* functions from app.core.tasks."""

from flask import request, jsonify

from ..core.tasks import (
    task_clean_bt_backup, task_check_stalled,
    task_clean_unmanaged, task_check_extensions,
    task_cleanup_quarantine, task_unmonitor_items,
    task_check_arr_health, task_sync_missing,
    task_send_notifications, task_send_digest,
    task_snapshot_metrics, task_clear_missing, task_clear_stalled, task_vacuum_db
)
from ..core.tasks._shared.timeouts import run_with_timeout, get_timeout
from ..core.tasks._shared import locks as task_lock
from . import bp
from ._shared import load_config

VALID_TASKS = {
    'bt_backup', 'unmanaged', 'extensions', 'missing', 'search', 'prune',
    'quarantine', 'unmonitor', 'arr_health', 'stalled', 'notify', 'digest',
    'metrics', 'db_clear_missing', 'db_clear_stalled', 'db_vacuum'
}

def _timeout(task_name):
    return get_timeout(task_name, load_config())

def _execute_task(task_name, dry_run):
    if task_name == 'bt_backup':
        count, msg, files = run_with_timeout('bt_backup', lambda: task_clean_bt_backup(dry_run=dry_run), _timeout('bt_backup'))
    elif task_name == 'unmanaged':
        count, msg, files = run_with_timeout('unmanaged', lambda: task_clean_unmanaged(dry_run=dry_run), _timeout('unmanaged'))
    elif task_name == 'extensions':
        count, msg, files = run_with_timeout('extensions', lambda: task_check_extensions(dry_run=dry_run), _timeout('extensions'))
    elif task_name == 'missing':
        count, msg, files = run_with_timeout('missing', lambda: task_sync_missing(mode='both', dry_run=dry_run), _timeout('missing'))
    elif task_name == 'search':
        count, msg, files = run_with_timeout('missing', lambda: task_sync_missing(mode='search', dry_run=dry_run), _timeout('missing'))
    elif task_name == 'prune':
        count, msg, files = run_with_timeout('missing', lambda: task_sync_missing(mode='prune', dry_run=dry_run), _timeout('missing'))
    elif task_name == 'quarantine':
        count, msg, files = run_with_timeout('quarantine', lambda: task_cleanup_quarantine(dry_run=dry_run), _timeout('quarantine'))
    elif task_name == 'unmonitor':
        count, msg, files = run_with_timeout('unmonitor', lambda: task_unmonitor_items(dry_run=dry_run), _timeout('unmonitor'))
    elif task_name == 'arr_health':
        count, msg, files = run_with_timeout('arr_health', lambda: task_check_arr_health(dry_run=dry_run), _timeout('arr_health'))
    elif task_name == 'notify':
        count, msg, files = run_with_timeout('notify', lambda: task_send_notifications(dry_run=dry_run), _timeout('notify'))
    elif task_name == 'digest':
        count, msg, files = run_with_timeout('digest', lambda: task_send_digest(dry_run=dry_run), _timeout('digest'))
    elif task_name == 'stalled':
        total, count = run_with_timeout('stalled', lambda: task_check_stalled(dry_run=dry_run), _timeout('stalled'))
        return f"Fetched {total} torrents. Monitoring {count} stalled.", []
    elif task_name == 'metrics':
        total = run_with_timeout('metrics', lambda: task_snapshot_metrics(dry_run=dry_run), _timeout('metrics'))
        return f"Snapshot written ({total} items tracked).", []
    elif task_name == 'db_clear_missing':
        count, msg, files = run_with_timeout('db_clear_missing', lambda: task_clear_missing(dry_run=dry_run), _timeout('metrics'))
        return msg, []
    elif task_name == 'db_clear_stalled':
        count, msg, files = run_with_timeout('db_clear_stalled', lambda: task_clear_stalled(dry_run=dry_run), _timeout('metrics'))
        return msg, []
    elif task_name == 'db_vacuum':
        count, msg, files = run_with_timeout('db_vacuum', lambda: task_vacuum_db(dry_run=dry_run), _timeout('metrics'))
        return msg, []
    else:
        return "Unknown task.", []
    return msg, files

@bp.route('/api/run-task', methods=['POST'])
def run_task():
    req_data = request.json
    task_name = req_data.get('task')
    dry_run = req_data.get('dry_run', False)

    if task_name not in VALID_TASKS:
        return jsonify({"status": "success", "message": "Unknown task.", "files": []})

    try:
        task_lock.acquire(task_name)
    except task_lock.TaskAlreadyRunning as e:
        return jsonify({"status": "error", "message": f"{e}. Try again later.", "files": []}), 409

    try:
        msg, files = _execute_task(task_name, dry_run)
    finally:
        task_lock.release(task_name)

    return jsonify({"status": "success", "message": msg, "files": files})
