"""Tests for admidio_db module."""

from pathlib import Path

from st_andreas.admidio_db import (
    AdmidioConfig,
    SSHConfig,
    load_db_config,
    load_secrets,
    load_ssh_config,
)


class TestLoadSecrets:
    """Tests for load_secrets function."""

    def test_parses_key_value_pairs(self, secrets_file: Path) -> None:
        # Arrange / Act
        result = load_secrets(secrets_file)

        # Assert
        assert result["ADMIDIO_DB_NAME"] == "test_db"
        assert result["ADMIDIO_DB_USER"] == "test_user"
        assert result["ADMIDIO_DB_PASSWORD"] == "test_password"

    def test_ignores_comments(self, secrets_file: Path) -> None:
        # Arrange / Act
        result = load_secrets(secrets_file)

        # Assert
        assert "# Test secrets file" not in result
        assert not any(k.startswith("#") for k in result)

    def test_ignores_empty_lines(self, secrets_file: Path) -> None:
        # Arrange / Act
        result = load_secrets(secrets_file)

        # Assert
        assert "" not in result

    def test_handles_values_with_equals_sign(self, tmp_path: Path) -> None:
        # Arrange
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text("KEY=value=with=equals\n")

        # Act
        result = load_secrets(secrets_file)

        # Assert
        assert result["KEY"] == "value=with=equals"


class TestLoadSSHConfig:
    """Tests for load_ssh_config function."""

    def test_creates_ssh_config_from_secrets(self, secrets_file: Path) -> None:
        # Arrange
        secrets = load_secrets(secrets_file)

        # Act
        result = load_ssh_config(secrets)

        # Assert
        assert isinstance(result, SSHConfig)
        assert result.host == "192.168.1.1"
        assert result.user == "testuser"
        assert result.key_path == "~/.ssh/test_key"


class TestLoadDBConfig:
    """Tests for load_db_config function."""

    def test_creates_db_config_from_secrets(self, secrets_file: Path) -> None:
        # Arrange
        secrets = load_secrets(secrets_file)

        # Act
        result = load_db_config(secrets)

        # Assert
        assert isinstance(result, AdmidioConfig)
        assert result.host == "127.0.0.1"
        assert result.database == "test_db"
        assert result.user == "test_user"
        assert result.password == "test_password"
        assert result.table_prefix == "adm_"
