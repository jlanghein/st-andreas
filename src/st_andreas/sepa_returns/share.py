"""Access to the MT940 exports and selection of the file to import.

Filename parsing and selection are pure; only the two source classes touch the
outside world.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

import smbclient
from smbprotocol.exceptions import SMBException

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from st_andreas.sepa_returns.config import ShareConfig

STATEMENT_PREFIX: Final[str] = "STA_"
STATEMENT_SUFFIX: Final[str] = ".sta"
EXPORT_TIMESTAMP_FORMAT: Final[str] = "%Y%m%d%H%M%S"

SMB_PATH_SEPARATOR: Final[str] = "\\"
SMB_UNC_PREFIX: Final[str] = SMB_PATH_SEPARATOR * 2
POSIX_PATH_SEPARATOR: Final[str] = "/"

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


def export_folder(config: ShareConfig) -> str:
    """Build the UNC path of the folder holding the exports."""
    path = config.path.replace(POSIX_PATH_SEPARATOR, SMB_PATH_SEPARATOR)
    return SMB_PATH_SEPARATOR.join(
        (f"{SMB_UNC_PREFIX}{config.host}", config.share, path)
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
    """Exports on the SternGeld SMB share, read through ``smbprotocol``.

    A pure-Python client rather than the Samba ``smbclient`` binary, which is
    absent on macOS and would make the host an install-time dependency.
    """

    config: ShareConfig

    def list_names(self) -> list[str]:
        """List the export file names in the configured share folder."""
        with self._connected() as folder:
            return [
                name
                for name in smbclient.listdir(folder)
                if STATEMENT_FILENAME_PATTERN.match(name)
            ]

    def read(self, name: str) -> bytes:
        """Download one export file and return its bytes."""
        with (
            self._connected() as folder,
            smbclient.open_file(
                f"{folder}{SMB_PATH_SEPARATOR}{name}", mode="rb"
            ) as handle,
        ):
            return handle.read()

    @contextmanager
    def _connected(self) -> Iterator[str]:
        """Hold a share session for one operation, yielding the export folder."""
        try:
            smbclient.register_session(
                self.config.host,
                username=self.config.user,
                password=self.config.password,
            )
            yield export_folder(self.config)
        except (OSError, SMBException) as error:
            raise ShareError(f"{export_folder(self.config)}: {error}") from error
        finally:
            smbclient.reset_connection_cache()
