"""SEPA transaction data fetching and transformation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from st_andreas.admidio_db import (
    AdmidioField,
    db_connection,
    fetch_field_value_list,
    fetch_user_field_values,
)
from st_andreas.sepa.config import (
    BEITRAG_EUR,
    Beitragsstufe,
    SepaConfig,
)

BEITRAGSSTUFE_FIELD_NAME: Final[str] = "BEITRAGSSTUFE"


@dataclass(frozen=True)
class MemberRecord:
    """Raw member data from Admidio database."""

    mitglieds_nr: str
    familien_nr: str | None
    vorname: str
    nachname: str
    iban: str | None
    bic: str | None
    kontoinhaber: str | None
    beitragsstufe: Beitragsstufe | None
    beitrag_bezahlt: bool


@dataclass(frozen=True)
class SepaTransaction:
    """A single SEPA direct debit transaction."""

    mandate_id: str
    debtor_name: str
    iban: str
    bic: str | None
    amount_eur: int
    payment_reference: str


def fetch_sepa_members(table_prefix: str, year: int) -> list[MemberRecord]:
    """Fetch member data required for SEPA direct debit from database."""
    beitrag_field = _get_beitrag_field_for_year(year)

    field_ids = [
        AdmidioField.MITGLIEDSNR.value,
        AdmidioField.FAMILIENNR.value,
        AdmidioField.FIRST_NAME.value,
        AdmidioField.LAST_NAME.value,
        AdmidioField.IBAN.value,
        AdmidioField.BIC.value,
        AdmidioField.KONTOINHABER.value,
        AdmidioField.BEITRAGSSTUFE.value,
        beitrag_field.value,
    ]

    with db_connection() as conn:
        users = fetch_user_field_values(conn, field_ids, table_prefix)
        beitragsstufe_mapping = fetch_field_value_list(
            conn, BEITRAGSSTUFE_FIELD_NAME, table_prefix
        )

    members: list[MemberRecord] = []
    for user_data in users.values():
        beitragsstufe = _parse_beitragsstufe(
            user_data.get(BEITRAGSSTUFE_FIELD_NAME),
            beitragsstufe_mapping,
        )

        beitrag_bezahlt_raw = user_data.get(beitrag_field.name)
        beitrag_bezahlt = beitrag_bezahlt_raw == "1" if beitrag_bezahlt_raw else False

        member = MemberRecord(
            mitglieds_nr=user_data.get("MITGLIEDSNR") or "",
            familien_nr=user_data.get("FAMILIENNR"),
            vorname=user_data.get("FIRST_NAME") or "",
            nachname=user_data.get("LAST_NAME") or "",
            iban=user_data.get("IBAN"),
            bic=user_data.get("BIC"),
            kontoinhaber=user_data.get("KONTOINHABER"),
            beitragsstufe=beitragsstufe,
            beitrag_bezahlt=beitrag_bezahlt,
        )
        members.append(member)

    return members


def build_transactions(
    members: list[MemberRecord],
    config: SepaConfig,
) -> tuple[list[SepaTransaction], list[MemberRecord]]:
    """Build SEPA transactions from member records.

    Returns a tuple of (valid transactions, members excluded due to missing IBAN).
    Deduplicates by mandate reference (families share one transaction).
    """
    transactions: list[SepaTransaction] = []
    excluded: list[MemberRecord] = []
    seen_mandate_ids: set[str] = set()

    for member in members:
        if member.beitrag_bezahlt:
            continue

        if not member.iban:
            excluded.append(member)
            continue

        if member.beitragsstufe is None:
            excluded.append(member)
            continue

        mandate_id = _resolve_mandate_id(member)
        if mandate_id in seen_mandate_ids:
            continue
        seen_mandate_ids.add(mandate_id)

        debtor_name = _resolve_debtor_name(member)
        amount = BEITRAG_EUR[member.beitragsstufe]
        payment_ref = config.payment_reference(member.beitragsstufe)

        transaction = SepaTransaction(
            mandate_id=mandate_id,
            debtor_name=debtor_name,
            iban=_normalize_iban(member.iban),
            bic=member.bic,
            amount_eur=amount,
            payment_reference=payment_ref,
        )
        transactions.append(transaction)

    return transactions, excluded


def _get_beitrag_field_for_year(year: int) -> AdmidioField:
    """Get the appropriate Beitrag bezahlt field for the given year."""
    year_to_field: dict[int, AdmidioField] = {
        2025: AdmidioField.BEITRAG_2025_BEZAHLT,
        2026: AdmidioField.BEITRAG_2026_BEZAHLT,
    }
    if year not in year_to_field:
        raise ValueError(f"No Beitrag field defined for year {year}")
    return year_to_field[year]


def _parse_beitragsstufe(
    raw_value: str | None,
    mapping: dict[str, str],
) -> Beitragsstufe | None:
    """Parse Beitragsstufe from database value."""
    if not raw_value:
        return None

    stufe_name = mapping.get(raw_value, "")

    if "Kinder" in stufe_name or "Jugend" in stufe_name:
        return Beitragsstufe.KINDER_JUGEND
    if "Erwachsene" in stufe_name:
        return Beitragsstufe.ERWACHSENE
    if "Familie" in stufe_name:
        return Beitragsstufe.FAMILIE
    if "Ermäßigt" in stufe_name:
        return Beitragsstufe.ERMAESSIGT
    if "Unterstützend" in stufe_name:
        return Beitragsstufe.UNTERSTUETZEND

    return None


def _resolve_mandate_id(member: MemberRecord) -> str:
    """Determine mandate reference for a member.

    Families (Beitragsstufe 3) use FamilienNr, others use MitgliedsNr.
    """
    if member.beitragsstufe == Beitragsstufe.FAMILIE and member.familien_nr:
        return member.familien_nr
    return member.mitglieds_nr


def _resolve_debtor_name(member: MemberRecord) -> str:
    """Determine debtor name for SEPA transaction.

    Uses KONTOINHABER if available, falls back to Vorname + Nachname.
    """
    if member.kontoinhaber:
        return member.kontoinhaber
    return f"{member.vorname} {member.nachname}"


def _normalize_iban(iban: str) -> str:
    """Remove spaces from IBAN."""
    return iban.replace(" ", "")
