"""Composable filters for member data pipelines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


class MemberFilter(ABC):
    """Base class for composable member filters."""

    @abstractmethod
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply filter to member DataFrame."""

    @abstractmethod
    def describe(self) -> str:
        """Human-readable filter description."""


@dataclass(frozen=True)
class FieldEmptyFilter(MemberFilter):
    """Filter for records where a field is empty/null."""

    field_name: str

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return df[df[self.field_name].isna() | (df[self.field_name] == "")]

    def describe(self) -> str:
        return f"{self.field_name} is empty"


@dataclass(frozen=True)
class FieldNotEmptyFilter(MemberFilter):
    """Filter for records where a field has a value."""

    field_name: str

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return df[df[self.field_name].notna() & (df[self.field_name] != "")]

    def describe(self) -> str:
        return f"{self.field_name} is not empty"


@dataclass(frozen=True)
class FieldEqualsFilter(MemberFilter):
    """Filter for records where field equals specific value(s)."""

    field_name: str
    values: tuple[str, ...]

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return df[df[self.field_name].isin(self.values)]

    def describe(self) -> str:
        if len(self.values) == 1:
            return f"{self.field_name} equals '{self.values[0]}'"
        return f"{self.field_name} in {self.values}"


@dataclass(frozen=True)
class FieldContainsFilter(MemberFilter):
    """Filter for records where field contains substring."""

    field_name: str
    substring: str

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return df[df[self.field_name].str.contains(self.substring, na=False)]

    def describe(self) -> str:
        return f"{self.field_name} contains '{self.substring}'"
