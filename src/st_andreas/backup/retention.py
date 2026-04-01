"""Backup retention and cleanup operations."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def find_expired_backups(backup_dir: Path, retention_days: int) -> list[Path]:
    """Find backup files older than retention period."""
    if not backup_dir.exists():
        return []

    cutoff = datetime.now() - timedelta(days=retention_days)
    expired: list[Path] = []

    for backup_file in backup_dir.glob("admidio_*.sql.gz"):
        file_mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
        if file_mtime < cutoff:
            expired.append(backup_file)

    return expired


def cleanup_old_backups(backup_dir: Path, retention_days: int) -> list[Path]:
    """Delete backups older than retention period, return deleted paths."""
    expired = find_expired_backups(backup_dir, retention_days)
    deleted: list[Path] = []

    for backup_file in expired:
        try:
            backup_file.unlink()
            deleted.append(backup_file)
            log.info("Deleted expired backup: %s", backup_file.name)
        except OSError:
            log.exception("Failed to delete backup: %s", backup_file.name)

    return deleted
