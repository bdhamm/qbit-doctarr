import sqlite3
import logging
from ...database import log_task_history, DB_PATH

logger = logging.getLogger(__name__)

def _execute_db_task(task_name, query, dry_run, table_name):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        cursor = conn.cursor()
        
        if dry_run:
            if table_name:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
            else:
                count = 0
            log_task_history(task_name, "Success", f"[DRY RUN] Would have affected {count} rows.")
            return count, f"Would affect {count} rows.", []
            
        if table_name:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            cursor.execute(f"DELETE FROM {table_name}")
            conn.commit()
            msg = f"Cleared {count} rows from {table_name}."
        else:
            # VACUUM cannot run inside a transaction
            conn.commit()
            cursor.execute("VACUUM;")
            msg = "Database vacuumed successfully."
            
        conn.close()
        logger.info(msg)
        log_task_history(task_name, "Success", msg)
        return 0, msg, []
    except Exception as e:
        logger.error(f"{task_name} failed: {e}")
        log_task_history(task_name, "Error", str(e))
        return 0, str(e), []

def task_clear_missing(dry_run=False):
    return _execute_db_task("Clear Missing Media", "DELETE", dry_run, "missing_media")

def task_clear_stalled(dry_run=False):
    return _execute_db_task("Clear Stalled Torrents", "DELETE", dry_run, "stalled_torrents")

def task_vacuum_db(dry_run=False):
    return _execute_db_task("Vacuum Database", "VACUUM", dry_run, None)
