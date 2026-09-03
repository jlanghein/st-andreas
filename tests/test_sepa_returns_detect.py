"""Tests for detecting returned direct debits."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from st_andreas.sepa_returns.detect import (
    OWN_BANK_RETURN_FEE_EUR,
    ReturnedDebit,
    detect_returns,
    returns_since,
)
from st_andreas.sepa_returns.mt940 import decode_statements, parse_statements

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mt940"
FULL_EXPORT = FIXTURE_DIR / "STA_1234567_50010517_20260902_060512.sta"

STATEMENT_HEADER = ":20:STARTUMS\n:25:50010517/1234567\n:28C:00001/001\n"


def build_statement(statement_line: str, information: str) -> str:
    return f"{STATEMENT_HEADER}:61:{statement_line}\n:86:{information}\n"


@pytest.fixture
def returns() -> list[ReturnedDebit]:
    return detect_returns(parse_statements(decode_statements(FULL_EXPORT.read_bytes())))


class TestDetectReturns:
    def test_finds_every_return_in_the_export(
        self, returns: list[ReturnedDebit]
    ) -> None:
        assert [debit.mandate_reference for debit in returns] == [
            "XY123456",
            "FA0042F",
            "ZZ999999",
            "AB010203",
        ]

    def test_ignores_the_collection_itself(self, returns: list[ReturnedDebit]) -> None:
        assert all(debit.booked_amount < Decimal("1000") for debit in returns)

    def test_reads_every_field_of_a_return(self, returns: list[ReturnedDebit]) -> None:
        debit = returns[0]

        assert debit.account == "50010517/1234567"
        assert debit.value_date == date(2026, 5, 13)
        assert debit.entry_date == date(2026, 5, 13)
        assert debit.booked_amount == Decimal("128.11")
        assert debit.original_amount == Decimal("120.00")
        assert debit.debtor_bank_fee == Decimal("3.00")
        assert debit.reason == "SONSTIGE GRUENDE"
        assert debit.beitrag_year == 2026
        assert debit.counterparty_name == "Müller, Erika und Max"

    def test_keeps_the_return_reason_of_an_objection(
        self, returns: list[ReturnedDebit]
    ) -> None:
        assert returns[1].reason == "WIDERSPRUCH DURCH ZAHLER"

    def test_missing_debtor_fee_stays_none(self, returns: list[ReturnedDebit]) -> None:
        assert returns[1].debtor_bank_fee is None

    def test_ignores_a_reversed_debit(self) -> None:
        # RD puts money back in, so it is not a returned collection.
        text = build_statement(
            "2605130513RD128,11NMSCNONREF",
            "109?00SEPA-LASTSCHR. RETOURE CORE?20MREF+XY123456",
        )

        assert detect_returns(parse_statements(text)) == []

    def test_ignores_another_business_transaction_code(self) -> None:
        text = build_statement(
            "2605130513DR128,11NMSCNONREF",
            "105?00SEPA-LASTSCHRIFT?20MREF+XY123456",
        )

        assert detect_returns(parse_statements(text)) == []

    def test_detects_a_reversed_credit(self, returns: list[ReturnedDebit]) -> None:
        assert returns[3].mandate_reference == "AB010203"

    def test_missing_mandate_reference_is_empty(self) -> None:
        text = build_statement(
            "2605130513DR128,11NMSCNONREF",
            "109?00SEPA-LASTSCHR. RETOURE CORE?20EREF+NOTPROVIDED",
        )

        assert detect_returns(parse_statements(text))[0].mandate_reference == ""


class TestBeitragYear:
    def test_reads_the_year_from_our_own_payment_reference(self) -> None:
        text = build_statement(
            "2601050105DR128,11NMSCNONREF",
            "109?00SEPA-LASTSCHR. RETOURE CORE"
            "?20MREF+XY123456?21SVWZ+SONSTIGE GRUENDE 2025 Beitrag St-Andreas Stufe 1",
        )

        assert detect_returns(parse_statements(text))[0].beitrag_year == 2025

    def test_falls_back_to_the_value_date_year(self) -> None:
        text = build_statement(
            "2601050105DR128,11NMSCNONREF",
            "109?00SEPA-LASTSCHR. RETOURE CORE?20MREF+XY123456?21SVWZ+RUECKGABE",
        )

        assert detect_returns(parse_statements(text))[0].beitrag_year == 2026


class TestAmountDecomposition:
    def test_own_bank_fee_is_the_remainder(
        self, returns: list[ReturnedDebit]
    ) -> None:
        assert returns[0].own_bank_fee == OWN_BANK_RETURN_FEE_EUR

    def test_expected_decomposition_reconciles(
        self, returns: list[ReturnedDebit]
    ) -> None:
        assert all(debit.amounts_reconcile for debit in returns)

    def test_an_unexpected_fee_does_not_reconcile(self) -> None:
        text = build_statement(
            "2605130513DR200,00NMSCNONREF",
            "109?00SEPA-LASTSCHR. RETOURE CORE?20MREF+XY123456?21OAMT+120,00",
        )

        assert not detect_returns(parse_statements(text))[0].amounts_reconcile


class TestFingerprint:
    def test_is_stable_for_the_same_booking(
        self, returns: list[ReturnedDebit]
    ) -> None:
        again = detect_returns(
            parse_statements(decode_statements(FULL_EXPORT.read_bytes()))
        )

        assert returns[0].fingerprint == again[0].fingerprint

    def test_differs_between_bookings(self, returns: list[ReturnedDebit]) -> None:
        assert len({debit.fingerprint for debit in returns}) == len(returns)

    def test_carries_the_identifying_values(
        self, returns: list[ReturnedDebit]
    ) -> None:
        assert returns[0].fingerprint == (
            "50010517/1234567|2026-05-13|2026-05-13|128.11|XY123456"
        )


class TestReturnsSince:
    def test_keeps_returns_on_or_after_the_cutoff(
        self, returns: list[ReturnedDebit]
    ) -> None:
        kept = returns_since(returns, date(2026, 6, 1))

        assert [debit.mandate_reference for debit in kept] == ["ZZ999999", "AB010203"]

    def test_keeps_everything_before_the_first_return(
        self, returns: list[ReturnedDebit]
    ) -> None:
        assert returns_since(returns, date(2026, 1, 1)) == returns
