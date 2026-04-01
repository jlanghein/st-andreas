"""Pipeline to generate donation receipts (Spendenquittungen) from Admidio data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Final

import pandas as pd

from st_andreas.admidio_db import (
    AdmidioField,
    db_connection,
    fetch_field_value_list,
    fetch_user_field_values,
    load_secrets,
    ssh_tunnel,
)

OUTPUT_DIR: Final = Path(__file__).parent.parent.parent / "data"


class Beitragsstufe(Enum):
    """Membership tier levels."""

    KINDER_JUGEND = 1
    ERWACHSENE = 2
    FAMILIE = 3
    ERMAESSIGT = 4
    UNTERSTUETZEND = 5


@dataclass(frozen=True)
class ReceiptConfig:
    """Configuration for donation receipt generation."""

    periode: int
    freistellungsbescheid_datum: date
    freistellungsbescheid_beginn: int
    freistellungsbescheid_ende: int


BEITRAG_EUR: Final[dict[Beitragsstufe, int]] = {
    Beitragsstufe.KINDER_JUGEND: 120,
    Beitragsstufe.ERWACHSENE: 120,
    Beitragsstufe.FAMILIE: 180,
    Beitragsstufe.ERMAESSIGT: 24,
    Beitragsstufe.UNTERSTUETZEND: 120,
}

BEITRAG_WORT: Final[dict[int, str]] = {
    24: "vierundzwanzig",
    48: "achtundvierzig",
    60: "sechzig",
    120: "einhundertundzwanzig",
    180: "einhundertundachtzig",
}

OUTPUT_COLUMNS: Final = [
    "Anrede",
    "Anschriftsname",
    "c/o",
    "Straße",
    "PLZ",
    "Ort",
    "Periode",
    "ID",
    "Beitragsstufe_EUR",
    "Beitragsstufe_Wort",
    "Freistellungsbescheiddatum",
    "Freistellungsbescheidbeginn",
    "Freistellungsbescheidende",
    "Pronomen",
]

RECEIPT_CONFIG: Final = ReceiptConfig(
    periode=2025,
    freistellungsbescheid_datum=date(2023, 12, 21),
    freistellungsbescheid_beginn=2020,
    freistellungsbescheid_ende=2022,
)


@dataclass
class MemberRecord:
    """Member data for receipt generation."""

    mitglieds_nr: str
    familien_nr: str | None
    vorname: str
    nachname: str
    anrede: str | None
    strasse: str | None
    plz: str | None
    ort: str | None
    geburtstag: date | None
    beitragsstufe: Beitragsstufe | None
    beitrag_bezahlt: bool


def fetch_member_data(table_prefix: str) -> list[MemberRecord]:
    """Fetch member data required for donation receipts from database."""
    field_ids = [
        AdmidioField.MITGLIEDSNR.value,
        AdmidioField.FAMILIENNR.value,
        AdmidioField.FIRST_NAME.value,
        AdmidioField.LAST_NAME.value,
        AdmidioField.ANREDE.value,
        AdmidioField.STREET.value,
        AdmidioField.POSTCODE.value,
        AdmidioField.CITY.value,
        AdmidioField.BIRTHDAY.value,
        AdmidioField.BEITRAGSSTUFE.value,
        AdmidioField.BEITRAG_2025_BEZAHLT.value,
    ]

    with db_connection() as conn:
        users = fetch_user_field_values(conn, field_ids, table_prefix)
        beitragsstufe_mapping = fetch_field_value_list(
            conn, "BEITRAGSSTUFE", table_prefix
        )
        anrede_mapping = fetch_field_value_list(conn, "ANREDE", table_prefix)

    members: list[MemberRecord] = []
    for user_data in users.values():
        beitragsstufe_raw = user_data.get("BEITRAGSSTUFE")
        beitragsstufe = _parse_beitragsstufe(beitragsstufe_raw, beitragsstufe_mapping)

        geburtstag_raw = user_data.get("BIRTHDAY")
        geburtstag = _parse_date(geburtstag_raw) if geburtstag_raw else None

        anrede_raw = user_data.get("ANREDE")
        anrede = anrede_mapping.get(anrede_raw) if anrede_raw else None

        beitrag_bezahlt_raw = user_data.get("BEITRAG_2025_BEZAHLT")
        beitrag_bezahlt = beitrag_bezahlt_raw == "1" if beitrag_bezahlt_raw else False

        member = MemberRecord(
            mitglieds_nr=user_data.get("MITGLIEDSNR") or "",
            familien_nr=user_data.get("FAMILIENNR"),
            vorname=user_data.get("FIRST_NAME") or "",
            nachname=user_data.get("LAST_NAME") or "",
            anrede=anrede,
            strasse=user_data.get("STREET"),
            plz=user_data.get("POSTCODE"),
            ort=user_data.get("CITY"),
            geburtstag=geburtstag,
            beitragsstufe=beitragsstufe,
            beitrag_bezahlt=beitrag_bezahlt,
        )
        members.append(member)

    return members


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


def _parse_date(date_str: str) -> date | None:
    """Parse date from database string format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def members_to_dataframe(members: list[MemberRecord]) -> pd.DataFrame:
    """Convert member records to DataFrame for processing."""
    records = [
        {
            "MitgliedsNr": m.mitglieds_nr,
            "FamilienNr": m.familien_nr,
            "Vorname": m.vorname,
            "Nachname": m.nachname,
            "Anrede": m.anrede,
            "Straße": m.strasse,
            "PLZ": m.plz,
            "Ort": m.ort,
            "Geburtstag": m.geburtstag,
            "Beitragsstufe": m.beitragsstufe.value if m.beitragsstufe else None,
            "Mitgliedsbeitrag_bezahlt": m.beitrag_bezahlt,
        }
        for m in members
    ]
    return pd.DataFrame(records)


def get_oldest_family_address(df: pd.DataFrame) -> pd.DataFrame:
    """Replace family members' addresses with the oldest family member's address."""
    families = df[df["Beitragsstufe"] == Beitragsstufe.FAMILIE.value]
    if families.empty:
        return df

    oldest_per_family = (
        families.sort_values("Geburtstag")
        .drop_duplicates(subset="FamilienNr", keep="first")
        .set_index("FamilienNr")[["Straße", "PLZ", "Ort"]]
    )

    result = df.copy()
    for col in ["Straße", "PLZ", "Ort"]:
        result[col] = (
            result["FamilienNr"].map(oldest_per_family[col]).fillna(result[col])
        )

    return result


def transform_for_receipts(df: pd.DataFrame, config: ReceiptConfig) -> pd.DataFrame:
    """Transform member data into receipt output format."""
    df = get_oldest_family_address(df)

    is_family = df["Beitragsstufe"] == Beitragsstufe.FAMILIE.value

    result = df.assign(
        Periode=config.periode,
        Freistellungsbescheiddatum=config.freistellungsbescheid_datum.strftime(
            "%d.%m.%Y"
        ),
        Freistellungsbescheidbeginn=config.freistellungsbescheid_beginn,
        Freistellungsbescheidende=config.freistellungsbescheid_ende,
        Anrede=lambda d: d["Anrede"].where(~is_family, "Familie"),
        Anschriftsname=df.apply(
            lambda row: (
                row["Nachname"]
                if row["Beitragsstufe"] == Beitragsstufe.FAMILIE.value
                else f"{row['Vorname']} {row['Nachname']}"
            ),
            axis=1,
        ),
        Beitragsstufe_EUR=df["Beitragsstufe"].map(
            {stufe.value: eur for stufe, eur in BEITRAG_EUR.items()}
        ),
        ID=df["FamilienNr"].where(is_family, df["MitgliedsNr"]),
        Pronomen=is_family.map({True: "Euren", False: "Deinen"}),
    )

    result["Beitragsstufe_Wort"] = result["Beitragsstufe_EUR"].map(BEITRAG_WORT)
    result["c/o"] = ""

    return (
        result.loc[result["Mitgliedsbeitrag_bezahlt"]]
        .drop_duplicates(subset="ID")
        .sort_values("Beitragsstufe_EUR")
        .loc[:, OUTPUT_COLUMNS]
    )


def main() -> None:
    """Generate donation receipts from Admidio database."""
    secrets = load_secrets()
    table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]

    with ssh_tunnel():
        members = fetch_member_data(table_prefix)

    df = members_to_dataframe(members)
    result = transform_for_receipts(df, RECEIPT_CONFIG)

    output_file = OUTPUT_DIR / f"Spendenquittungen_{RECEIPT_CONFIG.periode}.xlsx"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_excel(output_file, index=False)

    print(f"Generated {len(result)} receipts: {output_file}")


if __name__ == "__main__":
    main()
