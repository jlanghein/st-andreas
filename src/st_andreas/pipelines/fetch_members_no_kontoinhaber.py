"""Pipeline to fetch members without Kontoinhaber and export with email."""

from __future__ import annotations

from typing import Final

from st_andreas.admidio_db import AdmidioField
from st_andreas.member_pipeline import (
    ColumnConfig,
    FieldEmptyFilter,
    FilterFieldConfig,
    PipelineConfig,
    run_pipeline,
)

KONTOINHABER_COLUMN: Final[str] = "Kontoinhaber"

CONFIG: Final = PipelineConfig(
    name="members_no_kontoinhaber",
    description="Members without bank account holder information",
    columns=(
        ColumnConfig("MitgliedsNr", AdmidioField.MITGLIEDSNR, width=15),
        ColumnConfig("Nachname", AdmidioField.LAST_NAME, width=18),
        ColumnConfig("Vorname", AdmidioField.FIRST_NAME, width=18),
        ColumnConfig("Email", AdmidioField.EMAIL, width=30),
        ColumnConfig("FamilienNr", AdmidioField.FAMILIENNR, width=12),
        ColumnConfig("Sippe", AdmidioField.SIPPE, width=22),
    ),
    filter_fields=(FilterFieldConfig(KONTOINHABER_COLUMN, AdmidioField.KONTOINHABER),),
    filters=(FieldEmptyFilter(KONTOINHABER_COLUMN),),
    filename_prefix="Mitglieder_ohne_Kontoinhaber",
)


def main() -> None:
    """Main entry point for the members without Kontoinhaber pipeline."""
    run_pipeline(CONFIG)


if __name__ == "__main__":
    main()
