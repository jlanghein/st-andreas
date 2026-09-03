"""Tests for the MT940 parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from st_andreas.sepa_returns.mt940 import (
    EntryMark,
    MT940ParseError,
    SepaTag,
    Statement,
    decode_statements,
    parse_amount,
    parse_statements,
    split_sepa_tags,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mt940"
FULL_EXPORT = FIXTURE_DIR / "STA_1234567_50010517_20260902_060512.sta"

RETURN_PURPOSE = (
    "EREF+NOTPROVIDED"
    "KREF+0000000-000000000-0000"
    "1163-20260504"
    "MREF+XY123456"
    "COAM+3,00"
    "OAMT+120,00"
    "SVWZ+RETURN/REFUND  SONSTIGE GRUENDE 2026 Beitrag St-Andreas Stufe 1"
)


def load_fixture() -> list[Statement]:
    return parse_statements(decode_statements(FULL_EXPORT.read_bytes()))


@pytest.fixture
def statements() -> list[Statement]:
    return load_fixture()


class TestParseAmount:
    def test_parses_german_decimal_comma(self) -> None:
        assert parse_amount("128,11") == Decimal("128.11")

    def test_parses_thousands_without_separator(self) -> None:
        assert parse_amount("22560,00") == Decimal("22560.00")

    def test_rejects_garbage(self) -> None:
        with pytest.raises(MT940ParseError):
            parse_amount("not-a-number")


class TestSplitSepaTags:
    def test_mandate_reference_ends_at_the_next_known_tag(self) -> None:
        # COAM+ and OAMT+ must be known, or MREF+ swallows them.
        tags = split_sepa_tags(RETURN_PURPOSE)

        assert tags[SepaTag.MANDATE_REFERENCE.value] == "XY123456"

    def test_splits_the_amount_tags(self) -> None:
        tags = split_sepa_tags(RETURN_PURPOSE)

        assert tags[SepaTag.DEBTOR_BANK_FEE.value] == "3,00"
        assert tags[SepaTag.ORIGINAL_AMOUNT.value] == "120,00"

    def test_keeps_unknown_text_with_the_preceding_tag(self) -> None:
        tags = split_sepa_tags(RETURN_PURPOSE)

        assert tags[SepaTag.CUSTOMER_REFERENCE.value].endswith("1163-20260504")

    def test_returns_nothing_without_tags(self) -> None:
        assert split_sepa_tags("Sammellastschrift 2026") == {}


class TestParseStatements:
    def test_splits_on_the_statement_separator(self, statements: list[Statement]) -> None:
        assert len(statements) == 2

    def test_reads_the_account_identification(
        self, statements: list[Statement]
    ) -> None:
        assert statements[0].account == "50010517/1234567"

    def test_reads_the_statement_number(self, statements: list[Statement]) -> None:
        assert statements[0].number == "00042/001"

    def test_reads_the_opening_balance(self, statements: list[Statement]) -> None:
        opening = statements[0].opening_balance

        assert opening is not None
        assert opening.amount == Decimal("12345.67")
        assert opening.booking_date == date(2026, 5, 1)
        assert opening.currency == "EUR"

    def test_reads_an_interim_opening_balance(
        self, statements: list[Statement]
    ) -> None:
        opening = statements[1].opening_balance

        assert opening is not None
        assert opening.amount == Decimal("12000.00")

    def test_reads_the_closing_balance(self, statements: list[Statement]) -> None:
        closing = statements[1].closing_balance

        assert closing is not None
        assert closing.amount == Decimal("11800.00")

    def test_keeps_every_transaction(self, statements: list[Statement]) -> None:
        assert [len(statement.transactions) for statement in statements] == [4, 2]


class TestStatementLine:
    def test_parses_a_debit_with_a_funds_code(
        self, statements: list[Statement]
    ) -> None:
        transaction = statements[0].transactions[0]

        assert transaction.mark is EntryMark.DEBIT
        assert transaction.funds_code == "R"
        assert transaction.amount == Decimal("128.11")

    def test_parses_a_reversed_credit(self, statements: list[Statement]) -> None:
        transaction = statements[1].transactions[1]

        assert transaction.mark is EntryMark.REVERSAL_CREDIT
        assert transaction.funds_code == "R"
        assert transaction.amount == Decimal("128.11")

    def test_parses_value_and_entry_date(self, statements: list[Statement]) -> None:
        transaction = statements[0].transactions[0]

        assert transaction.value_date == date(2026, 5, 13)
        assert transaction.entry_date == date(2026, 5, 13)

    def test_entry_date_in_december_belongs_to_the_previous_year(self) -> None:
        text = (
            ":20:STARTUMS\n"
            ":25:50010517/1234567\n"
            ":28C:00001/001\n"
            ":61:2601021230DR10,00NMSCNONREF\n"
            ":86:109?00SEPA-LASTSCHR. RETOURE CORE\n"
        )

        transaction = parse_statements(text)[0].transactions[0]

        assert transaction.value_date == date(2026, 1, 2)
        assert transaction.entry_date == date(2025, 12, 30)

    def test_parses_a_reversed_debit(self) -> None:
        text = (
            ":20:STARTUMS\n"
            ":25:50010517/1234567\n"
            ":28C:00001/001\n"
            ":61:2605130513RD128,11NMSCNONREF\n"
            ":86:109?00SEPA-LASTSCHR. RETOURE CORE\n"
        )

        transaction = parse_statements(text)[0].transactions[0]

        assert transaction.mark is EntryMark.REVERSAL_DEBIT
        assert transaction.funds_code is None

    def test_rejects_a_malformed_statement_line(self) -> None:
        text = (
            ":20:STARTUMS\n"
            ":25:50010517/1234567\n"
            ":28C:00001/001\n"
            ":61:not-a-statement-line\n"
        )

        with pytest.raises(MT940ParseError):
            parse_statements(text)


class TestInformationField:
    def test_reads_the_business_transaction_code(
        self, statements: list[Statement]
    ) -> None:
        assert statements[0].transactions[0].business_transaction_code == "109"

    def test_reads_the_booking_text(self, statements: list[Statement]) -> None:
        assert (
            statements[0].transactions[0].booking_text
            == "SEPA-LASTSCHR. RETOURE CORE"
        )

    def test_joins_a_purpose_split_across_subfields(
        self, statements: list[Statement]
    ) -> None:
        purpose = statements[0].transactions[0].sepa_tag(SepaTag.PURPOSE)

        assert purpose is not None
        assert "SONSTIGE GRUENDE" in purpose
        assert "St-Andreas" in purpose

    def test_mandate_reference_survives_the_amount_tags(
        self, statements: list[Statement]
    ) -> None:
        transaction = statements[0].transactions[0]

        assert transaction.sepa_tag(SepaTag.MANDATE_REFERENCE) == "XY123456"

    def test_joins_the_counterparty_name(self, statements: list[Statement]) -> None:
        assert statements[0].transactions[0].counterparty_name == "Müller, Erika und Max"

    def test_reads_iban_and_bic(self, statements: list[Statement]) -> None:
        transaction = statements[0].transactions[0]

        assert transaction.counterparty_iban == "DE02500105170137075030"
        assert transaction.counterparty_bic == "GENODEF1S02"

    def test_missing_tag_is_none(self, statements: list[Statement]) -> None:
        family_return = statements[0].transactions[1]

        assert family_return.sepa_tag(SepaTag.DEBTOR_BANK_FEE) is None


class TestDecodeStatements:
    def test_decodes_latin1_umlauts(self) -> None:
        text = decode_statements("Müller".encode("latin-1"))

        assert text == "Müller"
