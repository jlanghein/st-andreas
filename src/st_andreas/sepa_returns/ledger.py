"""Persistent record of the returns that have already been applied.

Every daily export repeats the same return for about twelve months, so the
pipeline needs a memory of what it has acted on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, TypedDict

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from st_andreas.sepa_returns.detect import ReturnedDebit

LEDGER_VERSION: Final[int] = 1
LEDGER_ENCODING: Final[str] = "utf-8"
LEDGER_INDENT: Final[int] = 2
VERSION_KEY: Final[str] = "version"
ENTRIES_KEY: Final[str] = "entries"


class LedgerError(Exception):
    """Raised when a ledger file cannot be read."""


class LedgerRecord(TypedDict):
    """One applied return, as stored on disk."""

    fingerprint: str
    mandate_reference: str
    beitrag_year: int
    value_date: str
    booked_amount: str
    user_ids: list[int]
    applied_at: str


@dataclass(frozen=True)
class Ledger:
    """All returns the pipeline has applied so far."""

    entries: Mapping[str, LedgerRecord]

    def contains(self, fingerprint: str) -> bool:
        """Whether a return has already been applied."""
        return fingerprint in self.entries

    def extended(self, records: Iterable[LedgerRecord]) -> Ledger:
        """Return a new ledger with the given records added."""
        merged = dict(self.entries)
        for record in records:
            merged[record["fingerprint"]] = record
        return Ledger(entries=merged)


EMPTY_LEDGER: Final[Ledger] = Ledger(entries={})


def build_record(
    debit: ReturnedDebit,
    user_ids: Sequence[int],
    applied_at: datetime | None = None,
) -> LedgerRecord:
    """Build the ledger record for a return that has just been applied."""
    timestamp = applied_at or datetime.now(UTC)
    return LedgerRecord(
        fingerprint=debit.fingerprint,
        mandate_reference=debit.mandate_reference,
        beitrag_year=debit.beitrag_year,
        value_date=debit.value_date.isoformat(),
        booked_amount=str(debit.booked_amount),
        user_ids=list(user_ids),
        applied_at=timestamp.isoformat(),
    )


def encode_ledger(ledger: Ledger) -> str:
    """Serialize a ledger to its on-disk representation."""
    payload = {
        VERSION_KEY: LEDGER_VERSION,
        ENTRIES_KEY: sorted(ledger.entries.values(), key=lambda e: e["fingerprint"]),
    }
    return json.dumps(payload, indent=LEDGER_INDENT, ensure_ascii=False)


def decode_ledger(text: str) -> Ledger:
    """Parse a ledger from its on-disk representation."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise LedgerError(f"Ledger is not valid JSON: {error}") from error

    if not isinstance(payload, dict):
        raise LedgerError("Ledger must be a JSON object")

    version = payload.get(VERSION_KEY)
    if version != LEDGER_VERSION:
        raise LedgerError(f"Unsupported ledger version: {version!r}")

    records = payload.get(ENTRIES_KEY, [])
    if not isinstance(records, list):
        raise LedgerError("Ledger entries must be a JSON array")

    return Ledger(entries={_fingerprint_of(record): record for record in records})


def load_ledger(path: Path) -> Ledger:
    """Read the ledger, treating a missing file as an empty one."""
    if not path.exists():
        return EMPTY_LEDGER

    with path.open(encoding=LEDGER_ENCODING) as handle:
        return decode_ledger(handle.read())


def save_ledger(path: Path, ledger: Ledger) -> None:
    """Write the ledger, creating its directory when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=LEDGER_ENCODING) as handle:
        handle.write(encode_ledger(ledger))


def _fingerprint_of(record: object) -> str:
    if not isinstance(record, dict):
        raise LedgerError(f"Ledger entry must be a JSON object: {record!r}")
    fingerprint = record.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise LedgerError(f"Ledger entry has no fingerprint: {record!r}")
    return fingerprint
