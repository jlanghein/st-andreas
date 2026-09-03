"""Configuration for the SEPA returns pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_LEDGER_PATH: Final[Path] = (
    Path(__file__).parents[3] / "data" / "sepa_returns_ledger.json"
)
DEFAULT_TIMEZONE: Final[str] = "Europe/Berlin"
SCHEDULE_DAY: Final = "every monday"
DEFAULT_SCHEDULE_HOUR: Final[int] = 6
DEFAULT_SCHEDULE_MINUTE: Final[int] = 30
DEFAULT_SMTP_PORT: Final[int] = 587

ACCOUNT_IDENTIFIER_SEPARATOR: Final[str] = "/"

SHARE_SECRET_KEYS: Final[tuple[str, ...]] = (
    "STERNGELD_SMB_HOST",
    "STERNGELD_SMB_SHARE",
    "STERNGELD_SMB_USER",
    "STERNGELD_SMB_PASSWORD",
    "STERNGELD_SMB_PATH",
)
REPORT_RECIPIENT_KEY: Final[str] = "RETURNS_REPORT_TO"


@dataclass(frozen=True)
class ShareConfig:
    """Location of the StarMoney MT940 exports on the SternGeld SMB share."""

    host: str
    share: str
    user: str
    password: str
    path: str


@dataclass(frozen=True)
class AccountConfig:
    """The bank account whose statements we are allowed to import."""

    account_number: str
    bank_code: str

    @property
    def statement_identifier(self) -> str:
        """The value the ``:25:`` field must carry for our own statements."""
        return f"{self.bank_code}{ACCOUNT_IDENTIFIER_SEPARATOR}{self.account_number}"


@dataclass(frozen=True)
class ReportConfig:
    """Where the run summary is mailed to."""

    recipient: str
    sender: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str


@dataclass(frozen=True)
class ScheduleConfig:
    """Time of day of the weekly run."""

    hour: int
    minute: int
    timezone: str


@dataclass(frozen=True)
class ReturnsConfig:
    """Everything the returns pipeline needs to run."""

    account: AccountConfig
    share: ShareConfig | None
    report: ReportConfig | None
    schedule: ScheduleConfig
    ledger_path: Path


def load_share_config(secrets: dict[str, str]) -> ShareConfig | None:
    """Load the SMB share configuration, or None when it is not configured."""
    if any(not secrets.get(key) for key in SHARE_SECRET_KEYS):
        return None

    return ShareConfig(
        host=secrets["STERNGELD_SMB_HOST"],
        share=secrets["STERNGELD_SMB_SHARE"],
        user=secrets["STERNGELD_SMB_USER"],
        password=secrets["STERNGELD_SMB_PASSWORD"],
        path=secrets["STERNGELD_SMB_PATH"],
    )


def load_account_config(secrets: dict[str, str]) -> AccountConfig:
    """Load the account whose statements may be imported."""
    return AccountConfig(
        account_number=secrets["SEPA_ACCOUNT_NUMBER"],
        bank_code=secrets["SEPA_BLZ"],
    )


def load_report_config(secrets: dict[str, str]) -> ReportConfig | None:
    """Load the mail report configuration, or None when reporting is off."""
    recipient = secrets.get(REPORT_RECIPIENT_KEY)
    smtp_host = secrets.get("SMTP_HOST")
    if not recipient or not smtp_host:
        return None

    smtp_user = secrets.get("SMTP_USER", "")
    port = secrets.get("SMTP_PORT")

    return ReportConfig(
        recipient=recipient,
        sender=secrets.get("SMTP_FROM") or smtp_user,
        smtp_host=smtp_host,
        smtp_port=int(port) if port else DEFAULT_SMTP_PORT,
        smtp_user=smtp_user,
        smtp_password=secrets.get("SMTP_PASSWORD", ""),
    )


def load_schedule_config(secrets: dict[str, str]) -> ScheduleConfig:
    """Load the weekly schedule."""
    hour = secrets.get("RETURNS_SCHEDULE_HOUR")
    minute = secrets.get("RETURNS_SCHEDULE_MINUTE")

    return ScheduleConfig(
        hour=int(hour) if hour else DEFAULT_SCHEDULE_HOUR,
        minute=int(minute) if minute else DEFAULT_SCHEDULE_MINUTE,
        timezone=secrets.get("RETURNS_TIMEZONE", DEFAULT_TIMEZONE),
    )


def load_returns_config(secrets: dict[str, str]) -> ReturnsConfig:
    """Load the full pipeline configuration from secrets."""
    ledger_path = secrets.get("RETURNS_LEDGER_PATH")

    return ReturnsConfig(
        account=load_account_config(secrets),
        share=load_share_config(secrets),
        report=load_report_config(secrets),
        schedule=load_schedule_config(secrets),
        ledger_path=Path(ledger_path) if ledger_path else DEFAULT_LEDGER_PATH,
    )
