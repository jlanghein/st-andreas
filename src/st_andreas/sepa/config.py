"""Configuration for SEPA direct debit generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Final


class Beitragsstufe(Enum):
    """Membership fee tier levels."""

    KINDER_JUGEND = 1
    ERWACHSENE = 2
    FAMILIE = 3
    ERMAESSIGT = 4
    UNTERSTUETZEND = 5


BEITRAG_EUR: Final[dict[Beitragsstufe, int]] = {
    Beitragsstufe.KINDER_JUGEND: 120,
    Beitragsstufe.ERWACHSENE: 120,
    Beitragsstufe.FAMILIE: 180,
    Beitragsstufe.ERMAESSIGT: 24,
    Beitragsstufe.UNTERSTUETZEND: 120,
}


@dataclass(frozen=True)
class CreditorConfig:
    """SEPA creditor (payee) configuration."""

    name: str
    iban: str
    bic: str
    creditor_id: str


def load_creditor_config(secrets: dict[str, str]) -> CreditorConfig:
    """Load creditor configuration from secrets."""
    return CreditorConfig(
        name=secrets["SEPA_CREDITOR_NAME"],
        iban=secrets["SEPA_CREDITOR_IBAN"],
        bic=secrets["SEPA_CREDITOR_BIC"],
        creditor_id=secrets["SEPA_CREDITOR_ID"],
    )


@dataclass(frozen=True)
class SepaConfig:
    """Configuration for SEPA direct debit batch."""

    collection_date: date
    year: int
    creditor: CreditorConfig

    def payment_reference(self, beitragsstufe: Beitragsstufe) -> str:
        """Generate payment reference text for a transaction."""
        return f"{self.year} Beitrag St-Andreas Stufe {beitragsstufe.value}"
