import time
from pathlib import Path

from ...database import log_task_history
from ._shared.config import QUARANTINE_PATH, load_config
from ._shared.logging import logger, _log_full_and_truncated


def task_cleanup_quarantine(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    logger.info(f"Starting Quarantine Cleanup (Dry Run: {is_dry_run})...")
    retention_days = int(config.get("thresholds", {}).get("quarantine_retention_days", 7))
    if retention_days <= 0:
        logger.info("Quarantine retention is disabled (quarantine_retention_days=0). Skipping.")
        log_task_history("Quarantine Cleanup", "Success", "Disabled (quarantine_retention_days=0)")
        return 0, "Quarantine retention disabled.", []
    q_path = Path(QUARANTINE_PATH)
    if not q_path.is_dir():
        log_task_history("Quarantine Cleanup", "Error", "Quarantine directory not found")
        return 0, "Quarantine directory not found.", []
    cutoff_ts = time.time() - (retention_days * 86400)
    deleted = []
    errors = []
    for f in q_path.iterdir():
        if not f.is_file(): continue
        try:
            if f.stat().st_mtime < cutoff_ts:
                if not is_dry_run: f.unlink()
                deleted.append(f.name)
        except Exception as e:
            errors.append(f"{f.name}: {e}")
            logger.warning(f"Failed to remove quarantined file '{f.name}': {e}")
    deleted.sort()
    if not is_dry_run:
        action_str = f"Deleted {len(deleted)} file(s) older than {retention_days} day(s)"
    else:
        action_str = f"Would delete {len(deleted)} file(s) older than {retention_days} day(s)"
    extra = f" ({len(errors)} error(s) — see logs)" if errors else ""
    details = _log_full_and_truncated("Quarantine Cleanup", "Success", action_str, deleted, is_dry_run=is_dry_run, extra_suffix=extra)
    return len(deleted), details, deleted