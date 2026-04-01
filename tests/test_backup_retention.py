"""Tests for backup retention operations."""

import os
from datetime import datetime, timedelta
from pathlib import Path

from st_andreas.backup.retention import cleanup_old_backups, find_expired_backups


def set_file_mtime(path: Path, days_ago: int) -> None:
    """Set file modification time to specified days in the past."""
    target_time = datetime.now() - timedelta(days=days_ago)
    timestamp = target_time.timestamp()
    os.utime(path, (timestamp, timestamp))


class TestFindExpiredBackups:
    def test_returns_empty_for_nonexistent_directory(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "missing"

        result = find_expired_backups(nonexistent, retention_days=30)

        assert result == []

    def test_returns_empty_when_no_backups_exist(self, tmp_path: Path) -> None:
        result = find_expired_backups(tmp_path, retention_days=30)

        assert result == []

    def test_returns_empty_when_all_backups_recent(self, tmp_path: Path) -> None:
        recent_backup = tmp_path / "admidio_20250401_020000.sql.gz"
        recent_backup.touch()

        result = find_expired_backups(tmp_path, retention_days=30)

        assert result == []

    def test_finds_expired_backups(self, tmp_path: Path) -> None:
        old_backup = tmp_path / "admidio_20250101_020000.sql.gz"
        old_backup.touch()
        set_file_mtime(old_backup, days_ago=45)

        recent_backup = tmp_path / "admidio_20250401_020000.sql.gz"
        recent_backup.touch()

        result = find_expired_backups(tmp_path, retention_days=30)

        assert len(result) == 1
        assert result[0] == old_backup

    def test_ignores_non_backup_files(self, tmp_path: Path) -> None:
        old_file = tmp_path / "random_file.txt"
        old_file.touch()
        set_file_mtime(old_file, days_ago=45)

        result = find_expired_backups(tmp_path, retention_days=30)

        assert result == []


class TestCleanupOldBackups:
    def test_deletes_expired_backups(self, tmp_path: Path) -> None:
        old_backup = tmp_path / "admidio_20250101_020000.sql.gz"
        old_backup.touch()
        set_file_mtime(old_backup, days_ago=45)

        deleted = cleanup_old_backups(tmp_path, retention_days=30)

        assert len(deleted) == 1
        assert not old_backup.exists()

    def test_preserves_recent_backups(self, tmp_path: Path) -> None:
        recent_backup = tmp_path / "admidio_20250401_020000.sql.gz"
        recent_backup.touch()

        deleted = cleanup_old_backups(tmp_path, retention_days=30)

        assert deleted == []
        assert recent_backup.exists()

    def test_returns_list_of_deleted_paths(self, tmp_path: Path) -> None:
        old_backup_1 = tmp_path / "admidio_20250101_020000.sql.gz"
        old_backup_1.touch()
        set_file_mtime(old_backup_1, days_ago=45)

        old_backup_2 = tmp_path / "admidio_20250102_020000.sql.gz"
        old_backup_2.touch()
        set_file_mtime(old_backup_2, days_ago=44)

        deleted = cleanup_old_backups(tmp_path, retention_days=30)

        assert len(deleted) == 2
        assert old_backup_1 in deleted
        assert old_backup_2 in deleted
