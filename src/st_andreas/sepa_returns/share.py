"""Access to the MT940 exports and selection of the file to import.

Filename parsing and selection are pure; only the two source classes touch the
outside world.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from st_andreas.sepa_returns.config import ShareConfig

STATEMENT_PREFIX: Final[str] = "STA_"
STATEMENT_SUFFIX: Final[str] = ".sta"
EXPORT_TIMESTAMP_FORMAT: Final[str] = "%Y%m%d%H%M%S"

SMB_CLIENT_COMMAND: Final[str] = "smbclient"
SMB_PASSWORD_ENV_VAR: Final[str] = "PASSWD"
SMB_LIST_COMMAND: Final[str] = "ls"
SMB_GET_COMMAND: Final[str] = "get"
SMB_TIMEOUT_SECONDS: Final[int] = 300
SMB_UNC_PREFIX: Final[str] = "//"

STATEMENT_FILENAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^{re.escape(STATEMENT_PREFIX)}"
    r"(?P<account>[^_]+)_(?P<bank_code>[^_]+)"
    r"(?:_(?P<currency>[A-Z]{3}))?"
    r"_(?P<date>\d{8})_(?P<time>\d{6})"
    rf"{re.escape(STATEMENT_SUFFIX)}$"
)


class ShareError(Exception):
    """Raised when the export share cannot be read."""


@dataclass(frozen=True)
class StatementExport:
    """One MT940 export file on the share."""

    name: str
    account: str
    bank_code: str
    currency: str | None
    exported_at: datetime

    @property
    def covers_rolling_window(self) -> bool:
        """Whether this export carries the full rolling twelve months.

        StarMoney writes a second, currency-tagged export that holds the
        current year only, which would lose returns booked in December.
        """
        return self.currency is None


class StatementSource(Protocol):
    """Where statement exports are read from."""

    def list_names(self) -> list[str]: ...

    def read(self, name: str) -> bytes: ...


def parse_export_name(name: str) -> StatementExport | None:
    """Parse an export filename, returning None for anything else.

    Pending bookings (``VMK_``) fail this parse, which is what keeps money
    that has not moved out of the import.
    """
    match = STATEMENT_FILENAME_PATTERN.match(name)
    if match is None:
        return None

    return StatementExport(
        name=name,
        account=match.group("account"),
        bank_code=match.group("bank_code"),
        currency=match.group("currency"),
        exported_at=datetime.strptime(
            f"{match.group('date')}{match.group('time')}", EXPORT_TIMESTAMP_FORMAT
        ),
    )


def select_export(names: Iterable[str], account: str) -> StatementExport | None:
    """Pick the newest rolling-window export for the given account."""
    candidates = [
        export
        for export in (parse_export_name(name) for name in names)
        if export is not None
        and export.account == account
        and export.covers_rolling_window
    ]
    if not candidates:
        return None

    return max(candidates, key=lambda export: export.exported_at)


@dataclass(frozen=True)
class LocalDirectorySource:
    """Exports copied to a local directory, used for offline runs and tests."""

    directory: Path

    def list_names(self) -> list[str]:
        """List the file names in the directory."""
        return sorted(entry.name for entry in self.directory.iterdir())

    def read(self, name: str) -> bytes:
        """Read one export file."""
        return (self.directory / name).read_bytes()


@dataclass(frozen=True)
class SmbShareSource:
    """Exports on the SternGeld SMB share, read through ``smbclient``."""

    config: ShareConfig

    def list_names(self) -> list[str]:
        """List the file names in the configured share folder."""
        output = self._run(f"{SMB_LIST_COMMAND} {STATEMENT_PREFIX}*")
        return [
            name
            for name in (
                line.strip().split()[0] for line in output.splitlines() if line.strip()
            )
            if STATEMENT_FILENAME_PATTERN.match(name)
        ]

    def read(self, name: str) -> bytes:
        """Download one export file and return its bytes."""
        with TemporaryDirectory() as workdir:
            target = Path(workdir) / name
            self._run(f'{SMB_GET_COMMAND} "{name}" "{target}"')
            return target.read_bytes()

    def _run(self, command: str) -> str:
        share = f"{SMB_UNC_PREFIX}{self.config.host}/{self.config.share}"
        argv = [
            SMB_CLIENT_COMMAND,
            share,
            "-U",
            self.config.user,
            "-D",
            self.config.path,
            "-c",
            command,
        ]
        environment = os.environ | {SMB_PASSWORD_ENV_VAR: self.config.password}

        try:
            completed = subprocess.run(
                argv,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
                timeout=SMB_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as error:
            raise ShareError(
                f"{SMB_CLIENT_COMMAND} is not installed on this host"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ShareError(f"{share} did not answer in time") from error
        except subprocess.CalledProcessError as error:
            raise ShareError(f"{share}: {error.stderr.strip()}") from error

        return completed.stdout
