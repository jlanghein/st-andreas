"""Pipeline to fetch member data from Admidio and export to Excel."""

from __future__ import annotations

from typing import Final

from st_andreas.admidio_db import AdmidioField
from st_andreas.member_pipeline import ColumnConfig, PipelineConfig, run_pipeline

CONFIG: Final = PipelineConfig(
    name="fetch_members",
    description="All active members with basic information",
    columns=(
        ColumnConfig("MitgliedsNr", AdmidioField.MITGLIEDSNR, width=15),
        ColumnConfig("Nachname", AdmidioField.LAST_NAME, width=18),
        ColumnConfig("Vorname", AdmidioField.FIRST_NAME, width=18),
        ColumnConfig("Kontoinhaber", AdmidioField.KONTOINHABER, width=38),
        ColumnConfig("FamilienNr", AdmidioField.FAMILIENNR, width=12),
        ColumnConfig("Sippe", AdmidioField.SIPPE, width=22),
    ),
    sort_by=("Sippe", "Nachname"),
    filename_prefix="Mitgliederliste",
)


def main() -> None:
    """Main entry point for the member data pipeline."""
    run_pipeline(CONFIG)


if __name__ == "__main__":
    main()
