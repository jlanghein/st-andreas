"""Tests for backup configuration."""

from pathlib import Path

from st_andreas.backup.config import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SCHEDULE_HOUR,
    DEFAULT_SCHEDULE_MINUTE,
    DEFAULT_TIMEZONE,
    load_backup_config,
)


class TestLoadBackupConfig:
    def test_uses_defaults_when_not_specified(self) -> None:
        secrets = {"ADMIDIO_DB_ROOT_PASSWORD": "test_password"}

        config = load_backup_config(secrets)

        assert config.backup_dir == DEFAULT_BACKUP_DIR
        assert config.retention_days == DEFAULT_RETENTION_DAYS
        assert config.schedule_hour == DEFAULT_SCHEDULE_HOUR
        assert config.schedule_minute == DEFAULT_SCHEDULE_MINUTE
        assert config.timezone == DEFAULT_TIMEZONE

    def test_loads_custom_values_from_secrets(self) -> None:
        secrets = {
            "ADMIDIO_DB_ROOT_PASSWORD": "secret123",
            "BACKUP_DIR": "/custom/backups",
            "BACKUP_RETENTION_DAYS": "7",
            "BACKUP_TIME_HOUR": "4",
            "BACKUP_TIME_MINUTE": "30",
            "BACKUP_TIMEZONE": "UTC",
        }

        config = load_backup_config(secrets)

        assert config.backup_dir == Path("/custom/backups")
        assert config.retention_days == 7
        assert config.schedule_hour == 4
        assert config.schedule_minute == 30
        assert config.timezone == "UTC"
        assert config.db_root_password == "secret123"
