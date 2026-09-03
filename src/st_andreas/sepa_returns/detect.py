"""Detection of returned direct debits in parsed MT940 statements.

Pure functions only: a `Statement` in, `ReturnedDebit` values out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from st_andreas.sepa_returns.mt940 import EntryMark, SepaTag, Statement, parse_amount

if TYPE_CHECKING:
    from collections.abc import Iterable

    from st_andreas.sepa_returns.mt940 import Transaction

RETURN_TRANSACTION_CODE: Final[str] = "109"
OWN_BANK_RETURN_FEE_EUR: Final[Decimal] = Decimal("5.11")
RETURN_REASON_PREFIX: Final[str] = "RETURN/REFUND"
FINGERPRINT_SEPARATOR: Final[str] = "|"
NO_AMOUNT: Final[Decimal] = Decimal("0")

MONEY_LEAVES_ACCOUNT: Final[frozenset[EntryMark]] = frozenset(
    {EntryMark.DEBIT, EntryMark.REVERSAL_CREDIT}
)

# Must stay in sync with SepaConfig.payment_reference, which produced the text
# the bank echoes back in SVWZ.
PAYMENT_REFERENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<year>\d{4})\s+Beitrag\s+St-Andreas\s+Stufe\s*(?P<stufe>\d)"
)
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")


@dataclass(frozen=True)
class ReturnedDebit:
    """A membership fee direct debit the debtor's bank sent back."""

    account: str
    value_date: date
    entry_date: date
    booked_amount: Decimal
    mandate_reference: str
    end_to_end_reference: str
    original_amount: Decimal | None
    debtor_bank_fee: Decimal | None
    reason: str
    beitrag_year: int
    booking_text: str
    counterparty_name: str

    @property
    def fingerprint(self) -> str:
        """Stable identity of this return.

        MT940 carries no transaction id, so identity is the tuple that the bank
        cannot repeat for two different bookings.
        """
        parts = (
            self.account,
            self.value_date.isoformat(),
            self.entry_date.isoformat(),
            f"{self.booked_amount}",
            self.mandate_reference,
        )
        return FINGERPRINT_SEPARATOR.join(parts)

    @property
    def own_bank_fee(self) -> Decimal:
        """Share of the booked amount charged by our own bank."""
        original = self.original_amount or NO_AMOUNT
        debtor_fee = self.debtor_bank_fee or NO_AMOUNT
        return self.booked_amount - original - debtor_fee

    @property
    def amounts_reconcile(self) -> bool:
        """Whether the booked amount decomposes as expected."""
        return self.own_bank_fee == OWN_BANK_RETURN_FEE_EUR


def detect_returns(statements: Iterable[Statement]) -> list[ReturnedDebit]:
    """Find every returned direct debit across the given statements."""
    return [
        _build_returned_debit(statement.account, transaction)
        for statement in statements
        for transaction in statement.transactions
        if is_return(transaction)
    ]


def is_return(transaction: Transaction) -> bool:
    """Whether a transaction is a returned direct debit taking money back out."""
    return (
        transaction.business_transaction_code == RETURN_TRANSACTION_CODE
        and transaction.mark in MONEY_LEAVES_ACCOUNT
    )


def returns_since(debits: Iterable[ReturnedDebit], since: date) -> list[ReturnedDebit]:
    """Keep the returns booked on or after the given value date."""
    return [debit for debit in debits if debit.value_date >= since]


def _build_returned_debit(account: str, transaction: Transaction) -> ReturnedDebit:
    purpose = transaction.sepa_tag(SepaTag.PURPOSE) or ""

    return ReturnedDebit(
        account=account,
        value_date=transaction.value_date,
        entry_date=transaction.entry_date,
        booked_amount=transaction.amount,
        mandate_reference=transaction.sepa_tag(SepaTag.MANDATE_REFERENCE) or "",
        end_to_end_reference=transaction.sepa_tag(SepaTag.END_TO_END_REFERENCE) or "",
        original_amount=_optional_amount(transaction, SepaTag.ORIGINAL_AMOUNT),
        debtor_bank_fee=_optional_amount(transaction, SepaTag.DEBTOR_BANK_FEE),
        reason=_extract_reason(purpose),
        beitrag_year=_extract_year(purpose, transaction.value_date),
        booking_text=transaction.booking_text,
        counterparty_name=transaction.counterparty_name,
    )


def _optional_amount(transaction: Transaction, tag: SepaTag) -> Decimal | None:
    raw = transaction.sepa_tag(tag)
    return parse_amount(raw) if raw else None


def _extract_year(purpose: str, value_date: date) -> int:
    match = PAYMENT_REFERENCE_PATTERN.search(purpose)
    return int(match.group("year")) if match else value_date.year


def _extract_reason(purpose: str) -> str:
    match = PAYMENT_REFERENCE_PATTERN.search(purpose)
    reason = purpose[: match.start()] if match else purpose
    reason = reason.strip()
    if reason.startswith(RETURN_REASON_PREFIX):
        reason = reason[len(RETURN_REASON_PREFIX) :]
    return WHITESPACE_RUN_PATTERN.sub(" ", reason).strip()
