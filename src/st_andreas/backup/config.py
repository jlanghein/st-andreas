"""Backup configuration types and loaders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from st_andreas.admidio_db import load_secrets

DEFAULT_BACKUP_DIR: Final = Path(__file__).parent.parent.parent.parent / "backups"
DEFAULT_RETENTION_DAYS: Final = 30
DEFAULT_SCHEDULE_HOUR: Final = 2
DEFAULT_SCHEDULE_MINUTE: Final = 0
DEFAULT_TIMEZONE: Final = "Europe/Berlin"

DOCKER_CONTAINER_NAME: Final = "admidio_db"
MYSQLDUMP_DATABASE: Final = "admidio"


@dataclass
class BackupConfig:
    """Configuration for database backups."""

    backup_dir: Path
    retention_days: int
    schedule_hour: int
    schedule_minute: int
    timezone: str
    db_root_password: str


def load_backup_config(secrets: dict[str, str] | None = None) -> BackupConfig:
    """Load backup configuration from secrets and defaults."""
    if secrets is None:
        secrets = load_secrets()

    backup_dir_str = secrets.get("BACKUP_DIR")
    backup_dir = Path(backup_dir_str) if backup_dir_str else DEFAULT_BACKUP_DIR

    retention_str = secrets.get("BACKUP_RETENTION_DAYS")
    retention_days = int(retention_str) if retention_str else DEFAULT_RETENTION_DAYS

    hour_str = secrets.get("BACKUP_TIME_HOUR")
    schedule_hour = int(hour_str) if hour_str else DEFAULT_SCHEDULE_HOUR

    minute_str = secrets.get("BACKUP_TIME_MINUTE")
    schedule_minute = int(minute_str) if minute_str else DEFAULT_SCHEDULE_MINUTE

    timezone = secrets.get("BACKUP_TIMEZONE", DEFAULT_TIMEZONE)

    return BackupConfig(
        backup_dir=backup_dir,
        retention_days=retention_days,
        schedule_hour=schedule_hour,
        schedule_minute=schedule_minute,
        timezone=timezone,
        db_root_password=secrets["ADMIDIO_DB_ROOT_PASSWORD"],
    )
