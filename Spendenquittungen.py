#!/usr/bin/env python
from typing import NamedTuple
from datetime import datetime
from pandas import DataFrame, read_csv


class Metadata(NamedTuple):
    periode: int
    freistellungsgescheiddatum: datetime
    freistellungsbescheidbeginn: int
    freistellungsbescheidende: int


class BeitragsConfig(NamedTuple):
    stufe_mapper: dict[str, int]
    eur_mapper: dict[int, int]
    word_mapper: dict[int, str]


DATETIME_COLS = ["Beitrittsdatum", "Geburtstag"]

FAMILY_STUFE = "Stufe III: Familienbeitrag (180,-)"

METADATA = Metadata(
    periode=2025,
    freistellungsgescheiddatum=datetime(year=2023, month=12, day=21),
    freistellungsbescheidbeginn=2020,
    freistellungsbescheidende=2022,
)

BEITRAGS_CONFIG = BeitragsConfig(
    stufe_mapper={
        "Stufe I: Kinder- und Jugendbeitrag (120,-)": 1,
        "Stufe II: Erwachsenenbeitrag (120,-)": 2,
        FAMILY_STUFE: 3,
        "Stufe IV: Ermäßigter Beitrag (24,-)": 4,
        "Stufe V: Unterstützende Mitglieder (120,-)": 5,
    },
    eur_mapper={1: 120, 2: 120, 3: 180, 4: 24, 5: 120},
    word_mapper={
        120: "einhundertundzwanig",
        180: "einhundertundachtzig",
        24: "vierundzwanzig",
        48: "achtundvierzig",
        60: "sechzig",
    },
)

OUTPUT_COLS = [
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


def load_mitglieder_data(metadata: Metadata) -> DataFrame:
    return (
        read_csv("data/mitglieder.csv", parse_dates=DATETIME_COLS)
        .drop(columns=["Nr."])
        .rename(
            columns={f"Beitrag {metadata.periode} bezahlt": "Mitgliedsbeitrag_bezahlt"}
        )
    )


def get_oldest_family_address(df: DataFrame) -> DataFrame:
    families = df[df["Beitragsstufe"] == FAMILY_STUFE]
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


def transform_data_receipt(
    df: DataFrame, metadata: Metadata, config: BeitragsConfig
) -> DataFrame:
    df = get_oldest_family_address(df)

    return (
        df.assign(
            Beitragsstufe=lambda d: d["Beitragsstufe"].map(config.stufe_mapper),
            Periode=metadata.periode,
            Freistellungsbescheiddatum=metadata.freistellungsgescheiddatum.strftime(
                "%d.%m.%Y"
            ),
            Freistellungsbescheidbeginn=metadata.freistellungsbescheidbeginn,
            Freistellungsbescheidende=metadata.freistellungsbescheidende,
            Anrede=lambda d: d["Anrede"].where(d["Beitragsstufe"] != 3, "Familie"),
            Anschriftsname=lambda d: d.apply(
                lambda row: row["Nachname"]
                if row["Beitragsstufe"] == 3
                else f"{row['Vorname']} {row['Nachname']}",
                axis=1,
            ),
            Mitgliedsbeitrag_bezahlt=lambda d: d["Mitgliedsbeitrag_bezahlt"].astype(
                bool
            ),
            Beitragsstufe_EUR=lambda d: d["Beitragsstufe"]
            .astype(int)
            .map(config.eur_mapper),
            ID=lambda d: d["FamilienNr"].where(
                d["Beitragsstufe"] == 3, d["MitgliedsNr"]
            ),
        )
        .assign(
            Beitragsstufe_Wort=lambda d: d["Beitragsstufe_EUR"].map(config.word_mapper),
            Pronomen=lambda d: d["Beitragsstufe"].map({3: "Euren"}).fillna("Deinen"),
        )
        .loc[lambda d: d["Mitgliedsbeitrag_bezahlt"]]
        .drop_duplicates(subset="ID")
        .sort_values("Beitragsstufe_EUR")
        .loc[:, OUTPUT_COLS]
    )


def main() -> None:
    data = load_mitglieder_data(METADATA)
    result = transform_data_receipt(data, METADATA, BEITRAGS_CONFIG)
    output_file = f"data/Spendenquittungen_{METADATA.periode}.xlsx"
    result.to_excel(output_file, index=False)


if __name__ == "__main__":
    main()
