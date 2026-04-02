"""Tests for member pipeline filters."""

from __future__ import annotations

import pandas as pd
import pytest

from st_andreas.member_pipeline.filters import (
    FieldContainsFilter,
    FieldEmptyFilter,
    FieldEqualsFilter,
    FieldNotEmptyFilter,
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Sample DataFrame for filter testing."""
    return pd.DataFrame(
        {
            "Name": ["Alice", "Bob", "Charlie", "Diana"],
            "Email": ["alice@test.com", "", None, "diana@test.com"],
            "Status": ["active", "active", "inactive", "active"],
            "Notes": ["has SEPA", "pending review", "SEPA ready", None],
        }
    )


class TestFieldEmptyFilter:
    def test_filters_null_values(self, sample_df: pd.DataFrame) -> None:
        filter_ = FieldEmptyFilter("Email")

        result = filter_.apply(sample_df)

        assert len(result) == 2
        names = result["Name"].to_list()
        assert "Bob" in names
        assert "Charlie" in names

    def test_filters_empty_strings(self, sample_df: pd.DataFrame) -> None:
        filter_ = FieldEmptyFilter("Email")

        result = filter_.apply(sample_df)

        assert "Bob" in result["Name"].to_list()

    def test_describe(self) -> None:
        filter_ = FieldEmptyFilter("Kontoinhaber")

        assert filter_.describe() == "Kontoinhaber is empty"


class TestFieldNotEmptyFilter:
    def test_filters_non_empty_values(self, sample_df: pd.DataFrame) -> None:
        filter_ = FieldNotEmptyFilter("Email")

        result = filter_.apply(sample_df)

        assert len(result) == 2
        names = result["Name"].to_list()
        assert "Alice" in names
        assert "Diana" in names

    def test_describe(self) -> None:
        filter_ = FieldNotEmptyFilter("IBAN")

        assert filter_.describe() == "IBAN is not empty"


class TestFieldEqualsFilter:
    def test_filters_single_value(self, sample_df: pd.DataFrame) -> None:
        filter_ = FieldEqualsFilter("Status", ("active",))

        result = filter_.apply(sample_df)

        assert len(result) == 3
        assert "Charlie" not in result["Name"].to_list()

    def test_filters_multiple_values(self, sample_df: pd.DataFrame) -> None:
        filter_ = FieldEqualsFilter("Name", ("Alice", "Bob"))

        result = filter_.apply(sample_df)

        assert len(result) == 2
        names = result["Name"].to_list()
        assert "Alice" in names
        assert "Bob" in names

    def test_describe_single_value(self) -> None:
        filter_ = FieldEqualsFilter("Sippe", ("Adler",))

        assert filter_.describe() == "Sippe equals 'Adler'"

    def test_describe_multiple_values(self) -> None:
        filter_ = FieldEqualsFilter("Sippe", ("Adler", "Wolf"))

        assert filter_.describe() == "Sippe in ('Adler', 'Wolf')"


class TestFieldContainsFilter:
    def test_filters_substring(self, sample_df: pd.DataFrame) -> None:
        filter_ = FieldContainsFilter("Notes", "SEPA")

        result = filter_.apply(sample_df)

        assert len(result) == 2
        names = result["Name"].to_list()
        assert "Alice" in names
        assert "Charlie" in names

    def test_describe(self) -> None:
        filter_ = FieldContainsFilter("Notes", "pending")

        assert filter_.describe() == "Notes contains 'pending'"


class TestFilterComposition:
    def test_multiple_filters_applied_sequentially(
        self, sample_df: pd.DataFrame
    ) -> None:
        filters = [
            FieldNotEmptyFilter("Email"),
            FieldEqualsFilter("Status", ("active",)),
        ]

        result = sample_df
        for f in filters:
            result = f.apply(result)

        assert len(result) == 2
        names = result["Name"].to_list()
        assert "Alice" in names
        assert "Diana" in names
