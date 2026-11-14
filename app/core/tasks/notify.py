"""Email notification task and test helper."""

import smtplib
import sqlite3
from email.message import EmailMessage

from ...database import DB_PATH, log_task_history
from ._shared.config import load_config
from ._shared.logging import logger

TASK_NAME = "Notifications"

def _send_email(cfg, subject, body):
    host = (cfg.get("smtp_host") or "").strip()
    port = int(cfg.get("smtp_port", 25))
    tls_mode = (cfg.get("tls_mode") or "none").strip().lower()
    username = (cfg.get("username") or "").strip()
    password = cfg.get("password") or ""
    from_addr = (cfg.get("from_addr") or "").strip() or "qbit-doctarr@localhost"
    to_addrs = [a.strip() for a in (cfg.get("to_addrs") or "").split(",") if a.strip()]

    if not host: raise ValueError("SMTP host not configured")
    if not to_addrs: raise ValueError("No recipient addresses configured")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.set_content(body)

    if tls_mode == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            if username: server.login(username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if tls_mode == "starttls": server.starttls()
            if username: server.login(username, password)
            server.send_message(msg)

def send_test_email(config):
    """Fires a dummy email to test SMTP. Raises on failure."""
    notif = config.get("notifications") or {}
    email_cfg = notif.get("email") or {}
    subject = "[qbit-doctarr] Test Notification"
    body = "This is a test email from qbit-doctarr.\n\nIf you received this, your SMTP settings are configured correctly."
    _send_email(email_cfg, subject, body)
    logger.info("Test email sent successfully")

def suppress_historical_pending(sources=None):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        cursor = conn.cursor()
        if sources is None:
            cursor.execute("UPDATE arr_health_warnings SET notified_at=CURRENT_TIMESTAMP WHERE is_active=1 AND (notified_at IS NULL OR notified_at='')")
        else:
            sources = [str(s).strip() for s in sources if str(s).strip()]
            if not sources: return 0
            placeholders = ",".join(["?"] * len(sources))
            cursor.execute(f"UPDATE arr_health_warnings SET notified_at=CURRENT_TIMESTAMP WHERE is_active=1 AND (notified_at IS NULL OR notified_at='') AND source IN ({placeholders})", sources)
        count = cursor.rowcount
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        logger.error(f"Baseline suppression failed: {e}")
        return 0

def task_send_notifications(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    notif = config.get("notifications") or {}
    logger.info(f"Starting {TASK_NAME} (Dry Run: {is_dry_run})...")

    if not notif.get("enabled", False):
        msg = "Notifications disabled in settings."
        log_task_history(TASK_NAME, "Success", msg)
        return 0, msg, []

    email_cfg = notif.get("email") or {}
    muted = [str(m).strip() for m in (notif.get("muted_sources") or []) if str(m).strip()]
    muted_set = set(muted)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if muted:
        placeholders = ",".join(["?"] * len(muted))
        cursor.execute(f"SELECT id, arr_name, source, severity, message, first_seen FROM arr_health_warnings WHERE is_active=1 AND (notified_at IS NULL OR notified_at = '') AND source NOT IN ({placeholders})", muted)
    else:
        cursor.execute("SELECT id, arr_name, source, severity, message, first_seen FROM arr_health_warnings WHERE is_active=1 AND (notified_at IS NULL OR notified_at = '')")
    new_active = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT id, arr_name, source, severity, message, first_seen, last_seen FROM arr_health_warnings WHERE is_active=0 AND notified_at IS NOT NULL AND notified_at != ''")
    all_pending_resolved = [dict(r) for r in cursor.fetchall()]

    muted_resolved = [w for w in all_pending_resolved if w["source"] in muted_set]
    if muted_resolved:
        for w in muted_resolved:
            cursor.execute("UPDATE arr_health_warnings SET notified_at=NULL WHERE id=?", (w["id"],))
        conn.commit()
    new_resolved = [w for w in all_pending_resolved if w["source"] not in muted_set]
    conn.close()

    if not new_active and not new_resolved:
        msg = "No notification-worthy events."
        log_task_history(TASK_NAME, "Success", msg)
        return 0, msg, []

    parts = []
    if new_active: parts.append(f"{len(new_active)} new")
    if new_resolved: parts.append(f"{len(new_resolved)} resolved")
    subject = f"[qbit-doctarr] {' / '.join(parts)} health warning(s)"

    lines = []
    if new_active:
        lines.extend([f"NEW WARNINGS ({len(new_active)}):", ""])
        for w in new_active:
            lines.extend([f"  [{w['arr_name']}] {w['source']} ({w['severity']})", f"    {w['message']}", f"    First seen: {w['first_seen']}", ""])
    if new_resolved:
        lines.extend([f"RESOLVED ({len(new_resolved)}):", ""])
        for w in new_resolved:
            lines.extend([f"  [{w['arr_name']}] {w['source']} ({w['severity']})", f"    {w['message']}", f"    First seen: {w['first_seen']}", f"    Last seen:  {w['last_seen']}", ""])
    lines.extend(["--", "Sent by qbit-doctarr."])

    if is_dry_run:
        msg = f"[DRY RUN] Would notify: {len(new_active)} new, {len(new_resolved)} resolved."
        log_task_history(TASK_NAME, "Success", msg)
        return len(new_active) + len(new_resolved), msg, []

    try:
        _send_email(email_cfg, subject, "\n".join(lines))
    except Exception as e:
        log_task_history(TASK_NAME, "Error", f"Send failed: {e}")
        return 0, f"Send failed: {e}", []

    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        cursor = conn.cursor()
        for w in new_active: cursor.execute("UPDATE arr_health_warnings SET notified_at=CURRENT_TIMESTAMP WHERE id=?", (w["id"],))
        for w in new_resolved: cursor.execute("UPDATE arr_health_warnings SET notified_at=NULL WHERE id=?", (w["id"],))
        conn.commit()
        conn.close()
    except Exception as e: logger.error(f"Failed to update notified_at: {e}")

    summary = f"Sent notification: {len(new_active)} new, {len(new_resolved)} resolved."
    log_task_history(TASK_NAME, "Success", summary)
    return len(new_active) + len(new_resolved), summary, []
