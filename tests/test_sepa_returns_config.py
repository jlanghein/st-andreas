"""Tests for loading the returns pipeline configuration."""

from __future__ import annotations

from pathlib import Path

from st_andreas.sepa_returns.config import (
    DEFAULT_LEDGER_PATH,
    DEFAULT_SMTP_PORT,
    AccountConfig,
    load_returns_config,
)

FULL_SECRETS = {
    "SEPA_ACCOUNT_NUMBER": "1234567",
    "SEPA_BLZ": "50010517",
    "STERNGELD_SMB_HOST": "sterngeld.example",
    "STERNGELD_SMB_SHARE": "Daten",
    "STERNGELD_SMB_USER": "stamm",
    "STERNGELD_SMB_PASSWORD": "secret",
    "STERNGELD_SMB_PATH": "Kunden/StAndreas",
    "RETURNS_REPORT_TO": "kassenwart@example.org",
    "SMTP_HOST": "mail.example.org",
    "SMTP_USER": "bot@example.org",
    "SMTP_PASSWORD": "secret",
}


class TestAccountConfig:
    def test_builds_the_statement_identifier(self) -> None:
        account = AccountConfig(account_number="1234567", bank_code="50010517")

        assert account.statement_identifier == "50010517/1234567"


class TestLoadReturnsConfig:
    def test_loads_the_share(self) -> None:
        share = load_returns_config(dict(FULL_SECRETS)).share

        assert share is not None
        assert share.host == "sterngeld.example"
        assert share.path == "Kunden/StAndreas"

    def test_a_missing_share_key_disables_the_share(self) -> None:
        secrets = dict(FULL_SECRETS)
        del secrets["STERNGELD_SMB_PATH"]

        assert load_returns_config(secrets).share is None

    def test_loads_the_report_recipient(self) -> None:
        report = load_returns_config(dict(FULL_SECRETS)).report

        assert report is not None
        assert report.recipient == "kassenwart@example.org"
        assert report.sender == "bot@example.org"
        assert report.smtp_port == DEFAULT_SMTP_PORT

    def test_no_recipient_disables_reporting(self) -> None:
        secrets = dict(FULL_SECRETS)
        del secrets["RETURNS_REPORT_TO"]

        assert load_returns_config(secrets).report is None

    def test_falls_back_to_the_default_ledger_path(self) -> None:
        assert (
            load_returns_config(dict(FULL_SECRETS)).ledger_path == DEFAULT_LEDGER_PATH
        )

    def test_honours_a_configured_ledger_path(self) -> None:
        secrets = dict(FULL_SECRETS) | {"RETURNS_LEDGER_PATH": "/srv/returns.json"}

        assert load_returns_config(secrets).ledger_path == Path("/srv/returns.json")
