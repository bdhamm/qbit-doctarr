from pathlib import Path
from ...database import log_task_history
from ._shared.config import BT_BACKUP_PATH, load_config
from ._shared.qbit import move_to_quarantine
from ._shared.logging import logger, _log_full_and_truncated


def task_clean_bt_backup(dry_run=False):
    config = load_config()
    is_dry_run = dry_run or config.get("global_dry_run", False)
    logger.info(f"Starting BT_Backup scan (Dry Run: {is_dry_run})...")
    bt_dir = Path(BT_BACKUP_PATH)
    if not bt_dir.is_dir():
        log_task_history("BT_Backup Repair", "Error", "Directory not found")
        return 0, "Directory not found.", []
    inventory = {}
    for f in bt_dir.iterdir():
        if not f.is_file(): continue
        if f.suffix == ".torrent": inventory.setdefault(f.stem, {"t": False, "f": False})["t"] = True
        elif f.suffix == ".fastresume": inventory.setdefault(f.stem, {"t": False, "f": False})["f"] = True
    orphans = [bt_dir / f"{n}{'.torrent' if v['t'] else '.fastresume'}" for n, v in inventory.items() if v["t"] != v["f"]]
    orphan_names = [o.name for o in orphans]
    if not is_dry_run:
        for orphan in orphans: move_to_quarantine(orphan)
        action_str = f"Quarantined {len(orphans)} orphan files"
    else:
        action_str = f"Found {len(orphans)} orphan files"
    details = _log_full_and_truncated("BT_Backup Repair", "Success", action_str, orphan_names, is_dry_run=is_dry_run)
    return len(orphans), details, orphan_names