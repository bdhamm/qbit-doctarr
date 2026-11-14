import logging
from ....database import log_task_history

logger = logging.getLogger("app.core.tasks")


def _format_list(items, max_items=5):
    if not items: return ""
    items = [str(i) for i in items if i]
    if not items: return ""
    display = items[:max_items]
    suffix = f" ...and {len(items) - max_items} more" if len(items) > max_items else ""
    return ": " + ", ".join(display) + suffix


def _log_full_and_truncated(task_name, status, action_str, items, is_dry_run=False, extra_suffix=""):
    prefix = "[DRY RUN] " if is_dry_run else ""
    if items:
        logger.info(f"{prefix}{action_str}: {', '.join([str(i) for i in items])}{extra_suffix}")
    else:
        logger.info(f"{prefix}{action_str}{extra_suffix}")
    details = f"{prefix}{action_str}{_format_list(items)}{extra_suffix}."
    log_task_history(task_name, status, details)
    return details