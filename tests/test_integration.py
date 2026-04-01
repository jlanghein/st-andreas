"""Integration tests for database functions.

These tests require a running database connection via SSH tunnel.
They are skipped in CI environments where the database is not available.
"""

import os

import pytest

from st_andreas.admidio_db import (
    SECRETS_FILE,
    AdmidioField,
    db_connection,
    fetch_field_value_list,
    fetch_user_field_values,
    load_secrets,
    ssh_tunnel,
)

requires_database = pytest.mark.skipif(
    os.environ.get("CI") == "true" or not SECRETS_FILE.exists(),
    reason="Database tests require SSH tunnel and secrets file",
)


@requires_database
class TestSSHTunnel:
    """Integration tests for SSH tunnel."""

    def test_establishes_tunnel_and_cleans_up(self) -> None:
        # Arrange / Act / Assert
        with ssh_tunnel():
            pass


@requires_database
class TestDatabaseConnection:
    """Integration tests for database connection."""

    def test_connects_to_database(self) -> None:
        # Arrange / Act / Assert
        with ssh_tunnel(), db_connection() as conn:
            assert conn.open


@requires_database
class TestFetchFieldValueList:
    """Integration tests for fetch_field_value_list."""

    def test_fetches_beitragsstufe_mapping(self) -> None:
        # Arrange
        secrets = load_secrets()
        table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]

        # Act
        with ssh_tunnel(), db_connection() as conn:
            result = fetch_field_value_list(conn, "BEITRAGSSTUFE", table_prefix)

        # Assert
        assert len(result) > 0
        assert "1" in result
        assert "Stufe" in result["1"]

    def test_fetches_anrede_mapping(self) -> None:
        # Arrange
        secrets = load_secrets()
        table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]

        # Act
        with ssh_tunnel(), db_connection() as conn:
            result = fetch_field_value_list(conn, "ANREDE", table_prefix)

        # Assert
        assert len(result) > 0
        values = list(result.values())
        assert "Herr" in values or "Frau" in values


@requires_database
class TestFetchUserFieldValues:
    """Integration tests for fetch_user_field_values."""

    def test_fetches_user_data(self) -> None:
        # Arrange
        secrets = load_secrets()
        table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]
        field_ids = [
            AdmidioField.FIRST_NAME.value,
            AdmidioField.LAST_NAME.value,
        ]

        # Act
        with ssh_tunnel(), db_connection() as conn:
            result = fetch_user_field_values(conn, field_ids, table_prefix)

        # Assert
        assert len(result) > 0
        first_user = next(iter(result.values()))
        assert "FIRST_NAME" in first_user or "LAST_NAME" in first_user
