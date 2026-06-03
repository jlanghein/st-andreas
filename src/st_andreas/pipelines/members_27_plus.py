"""Pipeline to generate a report of members aged 27 and older."""

from __future__ import annotations

from typing import Final

from st_andreas.admidio_db import AdmidioField
from st_andreas.member_pipeline import (
    ColumnConfig,
    MinAgeFilter,
    PipelineConfig,
    run_pipeline,
)

MIN_AGE_YEARS: Final[int] = 27

CONFIG: Final = PipelineConfig(
    name="members_27_plus",
    description="Members aged 27+ with Beitragsstufe",
    columns=(
        ColumnConfig("Vorname", AdmidioField.FIRST_NAME, width=20),
        ColumnConfig("Nachname", AdmidioField.LAST_NAME, width=20),
        ColumnConfig("Geburtsdatum", AdmidioField.BIRTHDAY, width=15),
        ColumnConfig("Sippe", AdmidioField.SIPPE, width=22),
        ColumnConfig("Beitragsstufe", AdmidioField.BEITRAGSSTUFE, width=22),
    ),
    filters=(MinAgeFilter("Geburtsdatum", MIN_AGE_YEARS),),
    value_list_fields=("SIPPE", "BEITRAGSSTUFE"),
    sort_by=("Sippe", "Nachname"),
    filename_prefix="Mitglieder_ab_27",
)


def main() -> None:
    """Main entry point for the members 27+ pipeline."""
    run_pipeline(CONFIG)


if __name__ == "__main__":
    main()
