"""AioClock scheduler for daily database backups."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Final

from aioclock import AioClock, At, Once

from st_andreas.admidio_db import SSHConfig, load_secrets, load_ssh_config
from st_andreas.backup.config import BackupConfig, load_backup_config
from st_andreas.backup.dump import BackupError, create_backup
from st_andreas.backup.retention import cleanup_old_backups

log = logging.getLogger(__name__)

LOG_FORMAT: Final = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging() -> None:
    """Configure logging for the backup scheduler."""
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )


@asynccontextmanager
async def lifespan(app: AioClock) -> AsyncGenerator[AioClock]:
    """Scheduler lifecycle management."""
    log.info("Backup scheduler starting")
    yield app
    log.info("Backup scheduler shutting down")


def create_scheduler(
    backup_config: BackupConfig,
    ssh_config: SSHConfig,
    once: bool = False,
) -> AioClock:
    """Create and configure the AioClock scheduler."""
    app = AioClock(lifespan=lifespan)

    if once:
        trigger = Once()
    else:
        trigger = At(
            tz=backup_config.timezone,
            hour=backup_config.schedule_hour,
            minute=backup_config.schedule_minute,
            second=0,
        )

    @app.task(trigger=trigger)
    async def daily_backup() -> None:
        """Execute daily database backup and cleanup."""
        log.info("Starting scheduled backup")

        try:
            backup_path = await create_backup(ssh_config, backup_config)
            log.info("Backup completed: %s", backup_path.name)
        except BackupError:
            log.exception("Backup failed")
            return

        deleted = cleanup_old_backups(
            backup_config.backup_dir,
            backup_config.retention_days,
        )
        if deleted:
            log.info("Cleaned up %d expired backup(s)", len(deleted))

    return app


def main() -> None:
    """Entry point for backup scheduler CLI."""
    setup_logging()

    once = "--once" in sys.argv

    secrets = load_secrets()
    backup_config = load_backup_config(secrets)
    ssh_config = load_ssh_config(secrets)

    log.info(
        "Backup scheduled for %02d:%02d %s",
        backup_config.schedule_hour,
        backup_config.schedule_minute,
        backup_config.timezone,
    )
    log.info("Backup directory: %s", backup_config.backup_dir)
    log.info("Retention: %d days", backup_config.retention_days)

    if once:
        log.info("Running in one-shot mode")

    app = create_scheduler(backup_config, ssh_config, once=once)
    asyncio.run(app.serve())


if __name__ == "__main__":
    main()
