"""Pure MT940 statement parsing for German bank exports.

Parsing is free of I/O so it can be exercised from fixtures alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

STATEMENT_ENCODING: Final[str] = "latin-1"
STATEMENT_SEPARATOR: Final[str] = "-"
DECIMAL_SEPARATOR: Final[str] = ","
STATEMENT_CENTURY: Final[int] = 2000


class MT940ParseError(Exception):
    """Raised when a statement cannot be parsed."""


class FieldTag(StrEnum):
    """SWIFT field tags used by the statements we import."""

    TRANSACTION_REFERENCE = "20"
    ACCOUNT_IDENTIFICATION = "25"
    STATEMENT_NUMBER = "28C"
    OPENING_BALANCE = "60F"
    INTERIM_OPENING_BALANCE = "60M"
    STATEMENT_LINE = "61"
    INFORMATION = "86"
    CLOSING_BALANCE = "62F"
    INTERIM_CLOSING_BALANCE = "62M"


class EntryMark(StrEnum):
    """Debit/credit mark of a statement line.

    ``RC`` reverses a credit (money leaves the account), ``RD`` reverses a
    debit (money comes back in).
    """

    CREDIT = "C"
    DEBIT = "D"
    REVERSAL_CREDIT = "RC"
    REVERSAL_DEBIT = "RD"


class InfoSubfield(StrEnum):
    """``:86:`` subfield identifiers of the German ``?NN`` layout."""

    BOOKING_TEXT = "00"
    PRIMANOTA = "10"
    COUNTERPARTY_BIC = "30"
    COUNTERPARTY_IBAN = "31"
    COUNTERPARTY_NAME = "32"
    COUNTERPARTY_NAME_CONTINUED = "33"


class SepaTag(StrEnum):
    """SEPA tags embedded in the ``:86:`` purpose text.

    A tag's value ends at the next *known* tag, so an incomplete set silently
    swallows the following tags into the preceding value.
    """

    END_TO_END_REFERENCE = "EREF+"
    CUSTOMER_REFERENCE = "KREF+"
    MANDATE_REFERENCE = "MREF+"
    CREDITOR_ID = "CRED+"
    DEBTOR_ID = "DEBT+"
    PURPOSE = "SVWZ+"
    DEBTOR_BANK_FEE = "COAM+"
    ORIGINAL_AMOUNT = "OAMT+"
    DEVIATING_DEBTOR = "ABWA+"
    DEVIATING_CREDITOR = "ABWE+"


PURPOSE_SUBFIELD_IDS: Final[tuple[str, ...]] = tuple(
    f"{number:02d}" for number in range(20, 30)
)
COUNTERPARTY_NAME_SUBFIELD_IDS: Final[tuple[str, ...]] = (
    InfoSubfield.COUNTERPARTY_NAME.value,
    InfoSubfield.COUNTERPARTY_NAME_CONTINUED.value,
)

FIELD_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^:(?P<tag>[0-9A-Z]{2,3}):(?P<value>.*)$"
)
STATEMENT_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?P<value_date>\d{6})"
    r"(?P<entry_date>\d{4})?"
    r"(?P<mark>RC|RD|C|D)"
    r"(?P<funds_code>[A-Z])?"
    r"(?P<amount>[\d,]+)"
    r"(?P<transaction_type>[A-Z][A-Z0-9]{3})"
    r"(?P<reference>.*)$"
)
BALANCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?P<mark>[CD])(?P<date>\d{6})(?P<currency>[A-Z]{3})(?P<amount>[\d,]+)$"
)
INFORMATION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?P<code>\d{3})(?P<subfields>\?.*)?$", re.DOTALL
)
SUBFIELD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\?(?P<id>\d{2})(?P<value>[^?]*)", re.DOTALL
)
SEPA_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(
    "|".join(re.escape(tag.value) for tag in SepaTag)
)


@dataclass(frozen=True)
class Balance:
    """An opening or closing balance."""

    mark: EntryMark
    booking_date: date
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class Transaction:
    """A single booked statement line together with its ``:86:`` details."""

    value_date: date
    entry_date: date
    mark: EntryMark
    funds_code: str | None
    amount: Decimal
    transaction_type: str
    reference: str
    business_transaction_code: str
    booking_text: str
    purpose: str
    sepa_tags: Mapping[str, str]
    counterparty_name: str
    counterparty_iban: str
    counterparty_bic: str

    def sepa_tag(self, tag: SepaTag) -> str | None:
        """Return the value of a SEPA tag, or None when it is absent."""
        return self.sepa_tags.get(tag.value)


@dataclass(frozen=True)
class Statement:
    """One MT940 statement block."""

    reference: str
    account: str
    number: str
    opening_balance: Balance | None
    closing_balance: Balance | None
    transactions: tuple[Transaction, ...]


@dataclass(frozen=True)
class _Field:
    tag: str
    lines: tuple[str, ...]

    @property
    def joined(self) -> str:
        return "".join(self.lines)

    @property
    def first_line(self) -> str:
        return self.lines[0]


def decode_statements(raw: bytes) -> str:
    """Decode raw statement bytes using the encoding the bank writes."""
    return raw.decode(STATEMENT_ENCODING)


def parse_statements(text: str) -> list[Statement]:
    """Parse an MT940 export into its statement blocks."""
    return [
        _parse_statement(block)
        for block in _split_blocks(text)
        if any(field.tag == FieldTag.STATEMENT_NUMBER for field in block)
    ]


def parse_amount(raw: str) -> Decimal:
    """Parse a German decimal-comma amount."""
    try:
        return Decimal(raw.replace(DECIMAL_SEPARATOR, "."))
    except InvalidOperation as error:
        raise MT940ParseError(f"Not a valid amount: {raw!r}") from error


def split_sepa_tags(purpose: str) -> dict[str, str]:
    """Split a concatenated purpose text into its SEPA tags.

    Each value ends where the next known tag begins; the first occurrence of a
    tag wins.
    """
    matches = list(SEPA_TAG_PATTERN.finditer(purpose))
    tags: dict[str, str] = {}
    for position, match in enumerate(matches):
        is_last = position + 1 == len(matches)
        end = len(purpose) if is_last else matches[position + 1].start()
        tags.setdefault(match.group(0), purpose[match.end() : end].strip())
    return tags


def _split_blocks(text: str) -> list[list[_Field]]:
    blocks: list[list[_Field]] = []
    current: list[_Field] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if line.strip() == STATEMENT_SEPARATOR:
            blocks.append(current)
            current = []
            continue
        _append_line(current, line)

    blocks.append(current)
    return [block for block in blocks if block]


def _append_line(fields: list[_Field], line: str) -> None:
    match = FIELD_LINE_PATTERN.match(line)
    if match is not None:
        fields.append(_Field(tag=match.group("tag"), lines=(match.group("value"),)))
        return
    if not line or not fields:
        return
    previous = fields[-1]
    fields[-1] = _Field(tag=previous.tag, lines=(*previous.lines, line))


def _parse_statement(fields: Sequence[_Field]) -> Statement:
    by_tag = {field.tag: field for field in fields}

    return Statement(
        reference=_field_value(by_tag, FieldTag.TRANSACTION_REFERENCE),
        account=_field_value(by_tag, FieldTag.ACCOUNT_IDENTIFICATION),
        number=_field_value(by_tag, FieldTag.STATEMENT_NUMBER),
        opening_balance=_first_balance(
            by_tag, (FieldTag.OPENING_BALANCE, FieldTag.INTERIM_OPENING_BALANCE)
        ),
        closing_balance=_first_balance(
            by_tag, (FieldTag.CLOSING_BALANCE, FieldTag.INTERIM_CLOSING_BALANCE)
        ),
        transactions=tuple(_parse_transactions(fields)),
    )


def _field_value(by_tag: Mapping[str, _Field], tag: FieldTag) -> str:
    field = by_tag.get(tag.value)
    return field.joined if field is not None else ""


def _first_balance(
    by_tag: Mapping[str, _Field], tags: Iterable[FieldTag]
) -> Balance | None:
    for tag in tags:
        field = by_tag.get(tag.value)
        if field is not None:
            return _parse_balance(field.first_line)
    return None


def _parse_balance(value: str) -> Balance:
    match = BALANCE_PATTERN.match(value)
    if match is None:
        raise MT940ParseError(f"Not a valid balance field: {value!r}")

    return Balance(
        mark=EntryMark(match.group("mark")),
        booking_date=_parse_yymmdd(match.group("date")),
        currency=match.group("currency"),
        amount=parse_amount(match.group("amount")),
    )


def _parse_transactions(fields: Sequence[_Field]) -> list[Transaction]:
    transactions: list[Transaction] = []
    pending: _Field | None = None

    for field in fields:
        if field.tag == FieldTag.STATEMENT_LINE:
            if pending is not None:
                transactions.append(_build_transaction(pending, information=None))
            pending = field
            continue
        if field.tag == FieldTag.INFORMATION and pending is not None:
            transactions.append(_build_transaction(pending, information=field))
            pending = None

    if pending is not None:
        transactions.append(_build_transaction(pending, information=None))

    return transactions


def _build_transaction(line: _Field, information: _Field | None) -> Transaction:
    match = STATEMENT_LINE_PATTERN.match(line.first_line)
    if match is None:
        raise MT940ParseError(f"Not a valid statement line: {line.first_line!r}")

    value_date = _parse_yymmdd(match.group("value_date"))
    subfields = _parse_subfields(information.joined if information else "")
    purpose = "".join(subfields.get(key, "") for key in PURPOSE_SUBFIELD_IDS)

    return Transaction(
        value_date=value_date,
        entry_date=_parse_entry_date(value_date, match.group("entry_date")),
        mark=EntryMark(match.group("mark")),
        funds_code=match.group("funds_code"),
        amount=parse_amount(match.group("amount")),
        transaction_type=match.group("transaction_type"),
        reference=match.group("reference"),
        business_transaction_code=_business_transaction_code(information),
        booking_text=subfields.get(InfoSubfield.BOOKING_TEXT.value, "").strip(),
        purpose=purpose,
        sepa_tags=split_sepa_tags(purpose),
        counterparty_name="".join(
            subfields.get(key, "") for key in COUNTERPARTY_NAME_SUBFIELD_IDS
        ).strip(),
        counterparty_iban=subfields.get(
            InfoSubfield.COUNTERPARTY_IBAN.value, ""
        ).strip(),
        counterparty_bic=subfields.get(InfoSubfield.COUNTERPARTY_BIC.value, "").strip(),
    )


def _business_transaction_code(information: _Field | None) -> str:
    if information is None:
        return ""
    match = INFORMATION_PATTERN.match(information.joined)
    if match is None:
        raise MT940ParseError(f"Not a valid :86: field: {information.joined!r}")
    return match.group("code")


def _parse_subfields(information: str) -> dict[str, str]:
    subfields: dict[str, str] = {}
    for match in SUBFIELD_PATTERN.finditer(information):
        subfields.setdefault(match.group("id"), match.group("value"))
    return subfields


def _parse_yymmdd(raw: str) -> date:
    year = STATEMENT_CENTURY + int(raw[:2])
    return date(year, int(raw[2:4]), int(raw[4:6]))


def _parse_entry_date(value_date: date, raw: str | None) -> date:
    """Resolve the year-less entry date against the value date.

    An entry date in late December belongs to the previous year once the value
    date has rolled over, and the other way round in early January.
    """
    if raw is None:
        return value_date

    month, day = int(raw[:2]), int(raw[2:])
    candidates: list[date] = []
    for year in (value_date.year - 1, value_date.year, value_date.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue

    if not candidates:
        raise MT940ParseError(f"Not a valid entry date: {raw!r}")

    return min(candidates, key=lambda candidate: abs((candidate - value_date).days))
