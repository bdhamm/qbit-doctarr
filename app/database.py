import logging
import json
import sqlite3

logger = logging.getLogger(__name__)
DB_PATH = "/config/qbit-doctarr.db"
CONFIG_PATH = "/config/config.json"


def _table_exists(cursor, name):
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cursor.fetchone() is not None


def _columns(cursor, table):
    cursor.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def _ensure_columns(cursor, table, expected):
    """Add any missing columns to an existing table.

    `expected` is a dict of {column_name: 'sql type + default'}. Only runs
    ALTER TABLE for columns not already present, so it is safe on every
    install: no-op on fresh tables (all columns already exist), only acts
    on legacy tables missing newer columns. Returns the list of columns it
    actually added (empty list if nothing needed changing).
    """
    existing = set(_columns(cursor, table))
    added = []
    for col, ddl in expected.items():
        if col not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            added.append(col)
            logger.info(f"DB migration: added column {table}.{col}")
    return added


def init_db():
    """Create or upgrade every table. Idempotent on every run.

    Pattern per table:
      1. CREATE TABLE IF NOT EXISTS ...    (fresh install: creates; upgrade: no-op)
      2. _ensure_columns(...)              (fresh: no-op; upgrade: ALTERs only what's missing)

    Startup logs one of:
      'DB init: created table(s): ...'    if any table was newly created
      'DB init: upgraded existing table(s): ...'  if any column was added
      'DB init: all tables present, no changes'   on subsequent restarts
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA auto_vacuum = FULL;")

    created = []
    upgraded = []

    # ---------------------------------------------------------------- stalled_torrents
    was_new = not _table_exists(cursor, "stalled_torrents")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stalled_torrents (
            hash TEXT PRIMARY KEY,
            torrent_name TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT
        )
    ''')
    if was_new:
        created.append("stalled_torrents")
    else:
        if _ensure_columns(cursor, "stalled_torrents", {
            "torrent_name": "TEXT",
            "status": "TEXT",
        }):
            upgraded.append("stalled_torrents")

    # ---------------------------------------------------------------- task_history
    was_new = not _table_exists(cursor, "task_history")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT,
            last_run TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            details TEXT
        )
    ''')
    if was_new:
        created.append("task_history")

    # ---------------------------------------------------------------- missing_media
    was_new = not _table_exists(cursor, "missing_media")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS missing_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arr_name TEXT,
            item_type TEXT,
            item_id INTEGER,
            title TEXT,
            attempts INTEGER DEFAULT 0,
            last_searched TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
    ''')
    if was_new:
        created.append("missing_media")

    # ---------------------------------------------------------------- arr_health_warnings
    # notified_at tracks "have we told the user about this warning yet?"
    #   NULL on an active warning     -> un-notified, will be emailed
    #   set  on an active warning     -> already notified, stay quiet
    #   set  on an inactive warning   -> pending resolution notice
    #   NULL on an inactive warning   -> already resolved or never notified
    was_new = not _table_exists(cursor, "arr_health_warnings")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arr_health_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arr_name TEXT NOT NULL,
            source TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            wiki_url TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            notified_at TIMESTAMP,
            UNIQUE(arr_name, source, message)
        )
    ''')
    if was_new:
        created.append("arr_health_warnings")
    else:
        if _ensure_columns(cursor, "arr_health_warnings", {
            "notified_at": "TIMESTAMP",
        }):
            upgraded.append("arr_health_warnings")

    # ---------------------------------------------------------------- arr_health_status
    was_new = not _table_exists(cursor, "arr_health_status")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arr_health_status (
            arr_name TEXT PRIMARY KEY,
            last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_status TEXT NOT NULL DEFAULT 'unknown',
            last_error TEXT
        )
    ''')
    if was_new:
        created.append("arr_health_status")

    # ---------------------------------------------------------------- metrics_history (Task 8)
    # Hourly snapshots of dashboard counts, retained 30 days.
    # One row per snapshot; column-per-state mirrors the dashboard's two
    # stacked charts so the /trends page can rebuild them without joins.
    was_new = not _table_exists(cursor, "metrics_history")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            missing_active INTEGER DEFAULT 0,
            missing_failed INTEGER DEFAULT 0,
            missing_ignored INTEGER DEFAULT 0,
            stalled_dl INTEGER DEFAULT 0,
            stalled_meta INTEGER DEFAULT 0,
            stalled_seed INTEGER DEFAULT 0
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_metrics_history_snapshot_at "
        "ON metrics_history(snapshot_at)"
    )
    if was_new:
        created.append("metrics_history")

    # ---------------------------------------------------------------- one-time data migrations
    # Rename historical task_history entries to the current display name.
    # Idempotent: subsequent runs match zero rows.
    cursor.execute(
        "UPDATE task_history SET task_name = 'Database Health' "
        "WHERE task_name IN ('Arr Health', 'Arr DB Health', 'Arr Database Health')"
    )

    conn.commit()

    if created:
        logger.info(f"DB init: created table(s): {', '.join(created)}")
    if upgraded:
        logger.info(f"DB init: upgraded existing table(s): {', '.join(upgraded)}")
    if not created and not upgraded:
        logger.info("DB init: all tables present, no changes")

    # VACUUM cannot run inside a transaction. Commit first.
    cursor.execute("VACUUM;")
    conn.commit()
    conn.close()


def log_task_history(task_name, status, details):
    """Write a task_history row.

    `details` may be a plain string (legacy tasks, unchanged) or a dict
    (new structured format, serialized to JSON internally). Both forms
    are stored in the same TEXT column, so the DB schema needs no change.

    After the row is committed, a WAL checkpoint truncates the write-ahead
    log back to zero bytes. log_task_history is called once per task
    completion (a few times per day), so this is cheap and prevents the
    -wal file from growing unbounded between clean shutdowns.
    """
    try:
        if isinstance(details, dict):
            details_str = json.dumps(details)
        else:
            details_str = details

        history_limit = 100
        try:
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                history_limit = int(config.get("history_retention", 100))
        except Exception:
            pass

        conn = sqlite3.connect(DB_PATH, timeout=30)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO task_history (task_name, status, details) 
            VALUES (?, ?, ?)
        ''', (task_name, status, details_str))
        
        cursor.execute('''
            DELETE FROM task_history 
            WHERE id NOT IN (SELECT id FROM task_history ORDER BY id DESC LIMIT ?)
              AND id NOT IN (SELECT MAX(id) FROM task_history GROUP BY task_name)
        ''', (history_limit,))
        
        conn.commit()

        # Truncate WAL back to zero. May fail with SQLITE_BUSY if another
        # connection is mid-transaction; non-fatal, next completion retries.
        try:
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception as e:
            logger.warning(f"WAL checkpoint skipped: {e}")

        conn.close()
    except Exception as e:
        logger.error(f"Failed to log task history: {e}")


def parse_task_details(details):
    """Read a task_history.details value.

    Returns a tuple (structured_dict_or_None, display_string). Legacy rows
    (plain strings) return (None, original_string). New rows (JSON dicts)
    return (dict, summary field or repr fallback). Empty/None returns
    (None, "").
    """
    if not details:
        return None, ""
    try:
        parsed = json.loads(details)
        if isinstance(parsed, dict):
            return parsed, str(parsed.get("summary", "") or "")
    except (ValueError, TypeError):
        pass
    return None, str(details)
