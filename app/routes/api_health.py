"""Lightweight healthcheck endpoint for Docker.

Kept intentionally shallow: verifies the Flask app responds and the
background scheduler thread is alive. Deep DB checks belong on the
dashboard health card, not on a 60-second Docker probe.
"""

from flask import jsonify

from ..scheduler import scheduler
from . import bp


@bp.route('/api/health')
def health():
    sched_ok = bool(scheduler.running)
    status = "ok" if sched_ok else "degraded"
    code = 200 if sched_ok else 503
    body = {
        "status": status,
        "scheduler_running": sched_ok,
        "jobs": len(scheduler.get_jobs()) if sched_ok else 0,
    }
    return jsonify(body), code
