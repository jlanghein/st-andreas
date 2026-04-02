"""Configuration dataclasses for member pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from st_andreas.admidio_db import AdmidioField

if TYPE_CHECKING:
    from st_andreas.member_pipeline.filters import MemberFilter

DEFAULT_ADMIDIO_FOLDER_ID: Final[int] = 3
DEFAULT_COLUMN_WIDTH: Final[int] = 15


@dataclass(frozen=True)
class ColumnConfig:
    """Configuration for an output column."""

    header: str
    source_field: AdmidioField
    width: int = DEFAULT_COLUMN_WIDTH


@dataclass(frozen=True)
class FilterFieldConfig:
    """Configuration for a field used only for filtering (not exported)."""

    header: str
    source_field: AdmidioField


@dataclass(frozen=True)
class PipelineConfig:
    """Complete pipeline configuration."""

    name: str
    description: str
    columns: tuple[ColumnConfig, ...]
    filters: tuple[MemberFilter, ...] = field(default_factory=tuple)
    filter_fields: tuple[FilterFieldConfig, ...] = field(default_factory=tuple)
    sort_by: tuple[str, ...] = ("Sippe", "Nachname")
    upload_to_admidio: bool = True
    admidio_folder_id: int = DEFAULT_ADMIDIO_FOLDER_ID
    filename_prefix: str = "Mitgliederliste"
