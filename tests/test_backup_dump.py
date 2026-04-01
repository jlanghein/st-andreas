"""Tests for backup dump operations."""

import gzip
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from st_andreas.admidio_db import SSHConfig
from st_andreas.backup.config import BackupConfig
from st_andreas.backup.dump import (
    BackupError,
    build_backup_filename,
    build_mysqldump_command,
    build_ssh_command,
    create_backup,
    verify_backup,
)


class TestBuildBackupFilename:
    def test_formats_timestamp_correctly(self) -> None:
        timestamp = datetime(2025, 4, 1, 2, 30, 45)

        result = build_backup_filename(timestamp)

        assert result == "admidio_20250401_023045.sql.gz"


class TestBuildSshCommand:
    def test_builds_correct_command(self) -> None:
        config = SSHConfig(
            host="192.168.1.1",
            user="admin",
            key_path="~/.ssh/test_key",
        )

        result = build_ssh_command(config)

        assert result[0] == "ssh"
        assert "-i" in result
        assert "StrictHostKeyChecking=no" in result
        assert "BatchMode=yes" in result
        assert "admin@192.168.1.1" in result


class TestBuildMysqldumpCommand:
    def test_builds_correct_command(self) -> None:
        result = build_mysqldump_command("secret123")

        assert "docker exec admidio_db" in result
        assert "mysqldump" in result
        assert "-u root" in result
        assert "-psecret123" in result
        assert "admidio" in result


class TestVerifyBackup:
    def test_raises_when_file_missing(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "missing.sql.gz"

        with pytest.raises(BackupError, match="not created"):
            verify_backup(nonexistent)

    def test_raises_and_deletes_empty_file(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty.sql.gz"
        empty_file.touch()

        with pytest.raises(BackupError, match="empty"):
            verify_backup(empty_file)

        assert not empty_file.exists()

    def test_raises_and_deletes_invalid_gzip(self, tmp_path: Path) -> None:
        invalid_file = tmp_path / "invalid.sql.gz"
        invalid_file.write_bytes(b"not gzip content")

        with pytest.raises(BackupError, match="Invalid gzip"):
            verify_backup(invalid_file)

        assert not invalid_file.exists()

    def test_accepts_valid_gzip_with_content(self, tmp_path: Path) -> None:
        valid_file = tmp_path / "valid.sql.gz"
        with gzip.open(valid_file, "wb") as f:
            f.write(b"CREATE TABLE test;")

        verify_backup(valid_file)

        assert valid_file.exists()


class TestCreateBackup:
    @pytest.fixture
    def ssh_config(self) -> SSHConfig:
        return SSHConfig(
            host="test.example.com",
            user="testuser",
            key_path="/path/to/key",
        )

    @pytest.fixture
    def backup_config(self, tmp_path: Path) -> BackupConfig:
        return BackupConfig(
            backup_dir=tmp_path,
            retention_days=30,
            schedule_hour=2,
            schedule_minute=0,
            timezone="Europe/Berlin",
            db_root_password="testpass",
        )

    @pytest.mark.asyncio
    async def test_creates_compressed_backup(
        self,
        ssh_config: SSHConfig,
        backup_config: BackupConfig,
    ) -> None:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"CREATE TABLE users;", b""))

        with patch("st_andreas.backup.dump.asyncio.create_subprocess_exec") as mock:
            mock.return_value = mock_process
            timestamp = datetime(2025, 4, 1, 2, 0, 0)

            result = await create_backup(ssh_config, backup_config, timestamp)

            assert result.name == "admidio_20250401_020000.sql.gz"
            assert result.exists()
            with gzip.open(result, "rb") as f:
                assert f.read() == b"CREATE TABLE users;"

    @pytest.mark.asyncio
    async def test_raises_on_command_failure(
        self,
        ssh_config: SSHConfig,
        backup_config: BackupConfig,
    ) -> None:
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"Connection refused"))

        with patch("st_andreas.backup.dump.asyncio.create_subprocess_exec") as mock:
            mock.return_value = mock_process

            with pytest.raises(BackupError, match="Connection refused"):
                await create_backup(ssh_config, backup_config)

    @pytest.mark.asyncio
    async def test_raises_on_empty_output(
        self,
        ssh_config: SSHConfig,
        backup_config: BackupConfig,
    ) -> None:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch("st_andreas.backup.dump.asyncio.create_subprocess_exec") as mock:
            mock.return_value = mock_process

            with pytest.raises(BackupError, match="empty output"):
                await create_backup(ssh_config, backup_config)
