"""Database dump operations via SSH."""

from __future__ import annotations

import asyncio
import gzip
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from st_andreas.admidio_db import SSHConfig
from st_andreas.backup.config import DOCKER_CONTAINER_NAME, MYSQLDUMP_DATABASE

if TYPE_CHECKING:
    from st_andreas.backup.config import BackupConfig


class BackupError(Exception):
    """Raised when backup operation fails."""


def build_backup_filename(timestamp: datetime) -> str:
    """Generate backup filename with timestamp."""
    formatted = timestamp.strftime("%Y%m%d_%H%M%S")
    return f"admidio_{formatted}.sql.gz"


def build_ssh_command(ssh_config: SSHConfig) -> list[str]:
    """Build SSH command prefix for remote execution."""
    expanded_key_path = Path(ssh_config.key_path).expanduser()
    return [
        "ssh",
        "-i",
        str(expanded_key_path),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        f"{ssh_config.user}@{ssh_config.host}",
    ]


def build_mysqldump_command(db_root_password: str) -> str:
    """Build mysqldump command to run inside Docker container."""
    return (
        f"docker exec {DOCKER_CONTAINER_NAME} "
        f"mysqldump -u root -p{db_root_password} {MYSQLDUMP_DATABASE}"
    )


async def create_backup(
    ssh_config: SSHConfig,
    backup_config: BackupConfig,
    timestamp: datetime | None = None,
) -> Path:
    """Execute mysqldump via SSH and save compressed backup locally.

    Streams mysqldump output through SSH and compresses with gzip.
    """
    if timestamp is None:
        timestamp = datetime.now()

    backup_config.backup_dir.mkdir(parents=True, exist_ok=True)

    filename = build_backup_filename(timestamp)
    backup_path = backup_config.backup_dir / filename

    ssh_cmd = build_ssh_command(ssh_config)
    mysqldump_cmd = build_mysqldump_command(backup_config.db_root_password)
    full_command = [*ssh_cmd, mysqldump_cmd]

    process = await asyncio.create_subprocess_exec(
        *full_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown error"
        raise BackupError(f"mysqldump failed: {error_msg}")

    if not stdout:
        raise BackupError("mysqldump returned empty output")

    with gzip.open(backup_path, "wb") as f:
        f.write(stdout)

    verify_backup(backup_path)

    return backup_path


def verify_backup(backup_path: Path) -> None:
    """Verify backup file is valid gzip with content."""
    if not backup_path.exists():
        raise BackupError(f"Backup file not created: {backup_path}")

    if backup_path.stat().st_size == 0:
        backup_path.unlink()
        raise BackupError("Backup file is empty")

    try:
        with gzip.open(backup_path, "rb") as f:
            header = f.read(100)
            if not header:
                backup_path.unlink()
                raise BackupError("Backup file contains no data after decompression")
    except gzip.BadGzipFile as e:
        backup_path.unlink()
        raise BackupError(f"Invalid gzip file: {e}") from e
