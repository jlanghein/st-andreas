"""Tests for spendenquittungen module."""

from datetime import date

from inline_snapshot import snapshot

from st_andreas.spendenquittungen import (
    RECEIPT_CONFIG,
    Beitragsstufe,
    MemberRecord,
    _parse_beitragsstufe,
    _parse_date,
    get_oldest_family_address,
    members_to_dataframe,
    transform_for_receipts,
)


class TestParseBeitragsstufe:
    """Tests for _parse_beitragsstufe function."""

    def test_parses_kinder_jugend(self, beitragsstufe_mapping: dict[str, str]) -> None:
        # Arrange / Act
        result = _parse_beitragsstufe("1", beitragsstufe_mapping)

        # Assert
        assert result == Beitragsstufe.KINDER_JUGEND

    def test_parses_erwachsene(self, beitragsstufe_mapping: dict[str, str]) -> None:
        # Arrange / Act
        result = _parse_beitragsstufe("2", beitragsstufe_mapping)

        # Assert
        assert result == Beitragsstufe.ERWACHSENE

    def test_parses_familie(self, beitragsstufe_mapping: dict[str, str]) -> None:
        # Arrange / Act
        result = _parse_beitragsstufe("3", beitragsstufe_mapping)

        # Assert
        assert result == Beitragsstufe.FAMILIE

    def test_parses_ermaessigt(self, beitragsstufe_mapping: dict[str, str]) -> None:
        # Arrange / Act
        result = _parse_beitragsstufe("4", beitragsstufe_mapping)

        # Assert
        assert result == Beitragsstufe.ERMAESSIGT

    def test_parses_unterstuetzend(self, beitragsstufe_mapping: dict[str, str]) -> None:
        # Arrange / Act
        result = _parse_beitragsstufe("5", beitragsstufe_mapping)

        # Assert
        assert result == Beitragsstufe.UNTERSTUETZEND

    def test_returns_none_for_empty_value(
        self, beitragsstufe_mapping: dict[str, str]
    ) -> None:
        # Arrange / Act
        result = _parse_beitragsstufe(None, beitragsstufe_mapping)

        # Assert
        assert result is None

    def test_returns_none_for_unknown_value(
        self, beitragsstufe_mapping: dict[str, str]
    ) -> None:
        # Arrange / Act
        result = _parse_beitragsstufe("99", beitragsstufe_mapping)

        # Assert
        assert result is None


class TestParseDate:
    """Tests for _parse_date function."""

    def test_parses_valid_date(self) -> None:
        # Arrange / Act
        result = _parse_date("1990-05-15")

        # Assert
        assert result == date(1990, 5, 15)

    def test_returns_none_for_invalid_format(self) -> None:
        # Arrange / Act
        result = _parse_date("15.05.1990")

        # Assert
        assert result is None

    def test_returns_none_for_invalid_date(self) -> None:
        # Arrange / Act
        result = _parse_date("not-a-date")

        # Assert
        assert result is None


class TestMembersToDataframe:
    """Tests for members_to_dataframe function."""

    def test_converts_members_to_dataframe(
        self, sample_members: list[MemberRecord]
    ) -> None:
        # Arrange / Act
        result = members_to_dataframe(sample_members)

        # Assert
        assert len(result) == 4
        assert list(result.columns) == snapshot(
            [
                "MitgliedsNr",
                "FamilienNr",
                "Vorname",
                "Nachname",
                "Anrede",
                "Straße",
                "PLZ",
                "Ort",
                "Geburtstag",
                "Beitragsstufe",
                "Mitgliedsbeitrag_bezahlt",
            ]
        )

    def test_preserves_member_data(self, sample_members: list[MemberRecord]) -> None:
        # Arrange / Act
        result = members_to_dataframe(sample_members)

        # Assert
        first_row = result.iloc[0]
        assert first_row["MitgliedsNr"] == "JD010190"
        assert first_row["Vorname"] == "John"
        assert first_row["Nachname"] == "Doe"
        assert first_row["Beitragsstufe"] == Beitragsstufe.ERWACHSENE.value


class TestGetOldestFamilyAddress:
    """Tests for get_oldest_family_address function."""

    def test_replaces_family_addresses_with_oldest_members(
        self, sample_members: list[MemberRecord]
    ) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = get_oldest_family_address(df)

        # Assert
        family_members = result[result["FamilienNr"] == "FAM001"]
        assert len(family_members) == 2
        assert (family_members["Straße"] == "Family Lane 5").all()
        assert (family_members["PLZ"] == "54321").all()
        assert (family_members["Ort"] == "Munich").all()

    def test_preserves_non_family_addresses(
        self, sample_members: list[MemberRecord]
    ) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = get_oldest_family_address(df)

        # Assert
        non_family = result[result["FamilienNr"].isna()]
        john = non_family[non_family["MitgliedsNr"] == "JD010190"].iloc[0]
        assert john["Straße"] == "Main Street 1"
        assert john["PLZ"] == "12345"
        assert john["Ort"] == "Berlin"


class TestTransformForReceipts:
    """Tests for transform_for_receipts function."""

    def test_filters_only_paid_members(
        self, sample_members: list[MemberRecord]
    ) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = transform_for_receipts(df, RECEIPT_CONFIG)

        # Assert
        assert len(result) == 2

    def test_deduplicates_families_by_id(
        self, sample_members: list[MemberRecord]
    ) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = transform_for_receipts(df, RECEIPT_CONFIG)

        # Assert
        family_receipts = result[result["Anrede"] == "Familie"]
        assert len(family_receipts) == 1
        assert family_receipts.iloc[0]["ID"] == "FAM001"

    def test_family_uses_surname_only_as_anschriftsname(
        self, sample_members: list[MemberRecord]
    ) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = transform_for_receipts(df, RECEIPT_CONFIG)

        # Assert
        family = result[result["Anrede"] == "Familie"].iloc[0]
        assert family["Anschriftsname"] == "Doe"

    def test_non_family_uses_full_name_as_anschriftsname(
        self, sample_members: list[MemberRecord]
    ) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = transform_for_receipts(df, RECEIPT_CONFIG)

        # Assert
        individual = result[result["Anrede"] != "Familie"].iloc[0]
        assert individual["Anschriftsname"] == "John Doe"

    def test_sets_correct_beitrag_eur(self, sample_members: list[MemberRecord]) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = transform_for_receipts(df, RECEIPT_CONFIG)

        # Assert
        erwachsene = result[result["Anrede"] == "Herr"].iloc[0]
        assert erwachsene["Beitragsstufe_EUR"] == 120

        familie = result[result["Anrede"] == "Familie"].iloc[0]
        assert familie["Beitragsstufe_EUR"] == 180

    def test_sets_correct_pronomen(self, sample_members: list[MemberRecord]) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = transform_for_receipts(df, RECEIPT_CONFIG)

        # Assert
        individual = result[result["Anrede"] != "Familie"].iloc[0]
        assert individual["Pronomen"] == "Deinen"

        family = result[result["Anrede"] == "Familie"].iloc[0]
        assert family["Pronomen"] == "Euren"

    def test_output_has_correct_columns(
        self, sample_members: list[MemberRecord]
    ) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = transform_for_receipts(df, RECEIPT_CONFIG)

        # Assert
        assert list(result.columns) == snapshot(
            [
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
        )

    def test_sets_receipt_metadata(self, sample_members: list[MemberRecord]) -> None:
        # Arrange
        df = members_to_dataframe(sample_members)

        # Act
        result = transform_for_receipts(df, RECEIPT_CONFIG)

        # Assert
        row = result.iloc[0]
        assert row["Periode"] == 2025
        assert row["Freistellungsbescheiddatum"] == "21.12.2023"
        assert row["Freistellungsbescheidbeginn"] == 2020
        assert row["Freistellungsbescheidende"] == 2022
