"""Tests for export file selection and the local statement source."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from st_andreas.sepa_returns.share import (
    LocalDirectorySource,
    parse_export_name,
    select_export,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mt940"

ACCOUNT = "1234567"
ROLLING_WINDOW = "STA_1234567_50010517_20260902_060512.sta"
OLDER_ROLLING_WINDOW = "STA_1234567_50010517_20260901_060455.sta"
CURRENT_YEAR_ONLY = "STA_1234567_50010517_EUR_20260902_060520.sta"
PENDING = "VMK_1234567_50010517_20260902_060530.sta"
OTHER_ACCOUNT = "STA_7654321_50010517_20260902_060512.sta"


class TestParseExportName:
    def test_reads_account_bank_code_and_timestamp(self) -> None:
        export = parse_export_name(ROLLING_WINDOW)

        assert export is not None
        assert export.account == ACCOUNT
        assert export.bank_code == "50010517"
        assert export.exported_at == datetime(2026, 9, 2, 6, 5, 12)

    def test_an_export_without_a_currency_covers_the_rolling_window(self) -> None:
        export = parse_export_name(ROLLING_WINDOW)

        assert export is not None
        assert export.covers_rolling_window

    def test_a_currency_tagged_export_covers_the_current_year_only(self) -> None:
        export = parse_export_name(CURRENT_YEAR_ONLY)

        assert export is not None
        assert export.currency == "EUR"
        assert not export.covers_rolling_window

    def test_pending_bookings_are_not_an_export(self) -> None:
        assert parse_export_name(PENDING) is None

    def test_an_unrelated_file_is_not_an_export(self) -> None:
        assert parse_export_name("readme.txt") is None


class TestSelectExport:
    def test_picks_the_newest_rolling_window_export(self) -> None:
        export = select_export(
            [OLDER_ROLLING_WINDOW, ROLLING_WINDOW, CURRENT_YEAR_ONLY], ACCOUNT
        )

        assert export is not None
        assert export.name == ROLLING_WINDOW

    def test_skips_pending_bookings(self) -> None:
        assert select_export([PENDING], ACCOUNT) is None

    def test_skips_another_account(self) -> None:
        assert select_export([OTHER_ACCOUNT], ACCOUNT) is None

    def test_returns_nothing_for_an_empty_folder(self) -> None:
        assert select_export([], ACCOUNT) is None


class TestLocalDirectorySource:
    def test_lists_every_file(self) -> None:
        names = LocalDirectorySource(directory=FIXTURE_DIR).list_names()

        assert ROLLING_WINDOW in names
        assert PENDING in names

    def test_reads_a_file_verbatim(self) -> None:
        source = LocalDirectorySource(directory=FIXTURE_DIR)

        assert (
            source.read(ROLLING_WINDOW) == (FIXTURE_DIR / ROLLING_WINDOW).read_bytes()
        )
