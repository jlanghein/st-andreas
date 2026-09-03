"""Tests for the applied-returns ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from st_andreas.sepa_returns.detect import ReturnedDebit
from st_andreas.sepa_returns.ledger import (
    EMPTY_LEDGER,
    LedgerError,
    build_record,
    decode_ledger,
    encode_ledger,
    load_ledger,
    save_ledger,
)

DEBIT = ReturnedDebit(
    account="50010517/1234567",
    value_date=datetime(2026, 5, 13, tzinfo=UTC).date(),
    entry_date=datetime(2026, 5, 13, tzinfo=UTC).date(),
    booked_amount=Decimal("128.11"),
    mandate_reference="XY123456",
    end_to_end_reference="NOTPROVIDED",
    original_amount=Decimal("120.00"),
    debtor_bank_fee=Decimal("3.00"),
    reason="SONSTIGE GRUENDE",
    beitrag_year=2026,
    booking_text="SEPA-LASTSCHR. RETOURE CORE",
    counterparty_name="Erika Müller",
)
APPLIED_AT = datetime(2026, 5, 20, 6, 30, tzinfo=UTC)


class TestBuildRecord:
    def test_carries_the_fingerprint_and_users(self) -> None:
        record = build_record(DEBIT, [1, 2], applied_at=APPLIED_AT)

        assert record["fingerprint"] == DEBIT.fingerprint
        assert record["user_ids"] == [1, 2]
        assert record["applied_at"] == APPLIED_AT.isoformat()


class TestLedgerRoundTrip:
    def test_survives_encoding_and_decoding(self) -> None:
        ledger = EMPTY_LEDGER.extended([build_record(DEBIT, [1], APPLIED_AT)])

        restored = decode_ledger(encode_ledger(ledger))

        assert restored == ledger

    def test_contains_the_applied_fingerprint(self) -> None:
        ledger = EMPTY_LEDGER.extended([build_record(DEBIT, [1], APPLIED_AT)])

        assert ledger.contains(DEBIT.fingerprint)

    def test_empty_ledger_contains_nothing(self) -> None:
        assert not EMPTY_LEDGER.contains(DEBIT.fingerprint)

    def test_extending_leaves_the_original_untouched(self) -> None:
        EMPTY_LEDGER.extended([build_record(DEBIT, [1], APPLIED_AT)])

        assert EMPTY_LEDGER.entries == {}


class TestDecodeLedger:
    def test_rejects_broken_json(self) -> None:
        with pytest.raises(LedgerError):
            decode_ledger("{not json")

    def test_rejects_an_unknown_version(self) -> None:
        with pytest.raises(LedgerError):
            decode_ledger('{"version": 99, "entries": []}')

    def test_rejects_an_entry_without_a_fingerprint(self) -> None:
        with pytest.raises(LedgerError):
            decode_ledger('{"version": 1, "entries": [{"user_ids": [1]}]}')


class TestLedgerFile:
    def test_missing_file_reads_as_empty(self, tmp_path: Path) -> None:
        assert load_ledger(tmp_path / "absent.json") == EMPTY_LEDGER

    def test_saves_and_reloads(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "ledger.json"
        ledger = EMPTY_LEDGER.extended([build_record(DEBIT, [1], APPLIED_AT)])

        save_ledger(path, ledger)

        assert load_ledger(path) == ledger
