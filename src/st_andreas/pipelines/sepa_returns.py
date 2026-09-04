"""Pipeline that imports MT940 direct-debit returns and clears payment status.

Writing requires ``--apply <database>``: the operator has to name the database
they mean, so no default and no mistyped flag can reach production.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import smtplib
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from aioclock import AioClock, At, Once

from st_andreas.admidio_db import db_connection, load_secrets, ssh_tunnel
from st_andreas.sepa_returns.apply import AdmidioRepository
from st_andreas.sepa_returns.config import (
    SCHEDULE_DAY,
    ReturnsConfig,
    load_returns_config,
)
from st_andreas.sepa_returns.report import (
    build_subject,
    format_report,
    format_summary_line,
    send_report,
)
from st_andreas.sepa_returns.runner import (
    AccountMismatchError,
    RunRequest,
    RunResult,
    run_once,
)
from st_andreas.sepa_returns.share import (
    LocalDirectorySource,
    ShareError,
    SmbShareSource,
    StatementSource,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from datetime import date

log = logging.getLogger(__name__)

LOG_FORMAT: Final[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_ARGUMENT_FORMAT: Final[str] = "%Y-%m-%d"
SMB_LOGGER_NAME: Final[str] = "smbprotocol"
DATABASE_NAME_KEY: Final[str] = "ADMIDIO_DB_NAME"
TABLE_PREFIX_KEY: Final[str] = "ADMIDIO_TABLE_PREFIX"


class TargetMismatchError(Exception):
    """Raised when ``--apply`` names a database that is not configured."""

    def __init__(self, requested: str, configured: str) -> None:
        super().__init__(
            f"--apply {requested} does not match the configured database "
            f"{configured}; refusing to write"
        )
        self.requested = requested
        self.configured = configured


def resolve_write_target(requested: str | None, configured: str) -> str | None:
    """Return the database to write to, or None for a dry run."""
    if requested is None:
        return None
    if requested != configured:
        raise TargetMismatchError(requested, configured)
    return requested


def build_source(config: ReturnsConfig, directory: Path | None) -> StatementSource:
    """Choose between a local copy of the exports and the SMB share."""
    if directory is not None:
        return LocalDirectorySource(directory=directory)
    if config.share is None:
        raise ShareError(
            "No SMB share configured; set STERNGELD_SMB_* or use --from-directory"
        )
    return SmbShareSource(config=config.share)


def execute_cycle(
    config: ReturnsConfig,
    source: StatementSource,
    table_prefix: str,
    write_target: str | None,
    since: date | None,
) -> RunResult:
    """Run the pipeline once against the Admidio database."""
    with ssh_tunnel(), db_connection() as connection:
        repository = AdmidioRepository(connection=connection, table_prefix=table_prefix)
        return run_once(
            RunRequest(
                source=source,
                account=config.account,
                repository=repository,
                ledger_path=config.ledger_path,
                writer=repository if write_target else None,
                since=since,
            )
        )


def report_result(config: ReturnsConfig, result: RunResult) -> None:
    """Log every run and mail the ones that need a human."""
    log.info("%s (%s)", format_summary_line(result.summary), result.export.name)

    if not result.summary.needs_attention:
        return

    body = format_report(list(result.plans), result.summary)
    log.info("Returns needing attention:\n%s", body)

    if config.report is None:
        log.warning("No report recipient configured; summary stays in the log")
        return

    try:
        send_report(config.report, build_subject(result.summary), body)
    except (smtplib.SMTPException, OSError):
        log.exception("Could not mail the returns report")


def setup_logging() -> None:
    """Configure logging for the returns pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Thirty lines of SMB handshake per run would bury the one line that matters.
    logging.getLogger(SMB_LOGGER_NAME).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: AioClock) -> AsyncGenerator[AioClock]:
    """Scheduler lifecycle management."""
    log.info("SEPA returns scheduler starting")
    yield app
    log.info("SEPA returns scheduler shutting down")


def create_scheduler(
    config: ReturnsConfig,
    source: StatementSource,
    table_prefix: str,
    write_target: str | None,
    since: date | None,
    once: bool = False,
) -> AioClock:
    """Create the AioClock app that runs the import weekly."""
    app = AioClock(lifespan=lifespan)

    trigger = (
        Once()
        if once
        else At(
            tz=config.schedule.timezone,
            at=SCHEDULE_DAY,
            hour=config.schedule.hour,
            minute=config.schedule.minute,
            second=0,
        )
    )

    @app.task(trigger=trigger)
    async def weekly_returns_import() -> None:
        """Import the newest export and reconcile the returns it contains."""
        try:
            result = execute_cycle(config, source, table_prefix, write_target, since)
        except (ShareError, AccountMismatchError):
            log.exception("Returns import failed")
            return

        report_result(config, result)

    return app


def main() -> None:
    """Entry point for the SEPA returns pipeline."""
    setup_logging()
    args = _parse_args()

    secrets = load_secrets()
    config = load_returns_config(secrets)
    if args.ledger is not None:
        config = ReturnsConfig(
            account=config.account,
            share=config.share,
            report=config.report,
            schedule=config.schedule,
            ledger_path=args.ledger,
        )

    write_target = resolve_write_target(args.apply, secrets[DATABASE_NAME_KEY])
    source = build_source(config, args.from_directory)

    if write_target is None:
        log.info("Dry run: no writes; pass --apply <database> to reconcile")
    else:
        log.info("Writing to database %s", write_target)

    app = create_scheduler(
        config,
        source,
        secrets[TABLE_PREFIX_KEY],
        write_target,
        args.since,
        once=args.once,
    )
    asyncio.run(app.serve())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import returned SEPA direct debits and reset payment status"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single import instead of the weekly schedule",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Report what would change without writing (the default)",
    )
    parser.add_argument(
        "--apply",
        metavar="DATABASE",
        help="Write to the named Admidio database; must match ADMIDIO_DB_NAME",
    )
    parser.add_argument(
        "--since",
        type=_parse_date,
        help="Ignore returns with a value date before this day (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--from-directory",
        type=Path,
        help="Read the exports from a local directory instead of the SMB share",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        help="Path of the applied-returns ledger",
    )

    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    return args


def _parse_date(value: str) -> date:
    return datetime.strptime(value, DATE_ARGUMENT_FORMAT).date()


if __name__ == "__main__":
    main()
