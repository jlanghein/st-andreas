"""Run summary and the mail that carries it to the treasurer.

Admidio state alone cannot surface these cases: a returned debit often
coincides with the member leaving, and every member report filters to active
members.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING, Final

from st_andreas.sepa_returns.apply import PlanStatus, format_amount

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from st_andreas.sepa_returns.apply import ReturnPlan
    from st_andreas.sepa_returns.config import ReportConfig

REPORT_SUBJECT: Final[str] = "SEPA-Rücklastschriften: {new} neu, {open} offen"
REPORT_DATE_FORMAT: Final[str] = "%d.%m.%Y"
DRY_RUN_NOTICE: Final[str] = "Dry run - nothing was written."

ATTENTION_STATUSES: Final[tuple[PlanStatus, ...]] = (
    PlanStatus.APPLICABLE,
    PlanStatus.AMBIGUOUS,
    PlanStatus.UNRESOLVED,
    PlanStatus.UNKNOWN_YEAR,
)
SECTION_TITLES: Final[dict[PlanStatus, str]] = {
    PlanStatus.APPLICABLE: "Neu verarbeitet",
    PlanStatus.AMBIGUOUS: "Nicht eindeutig - nicht geschrieben",
    PlanStatus.UNRESOLVED: "Kein Mitglied gefunden - nicht geschrieben",
    PlanStatus.UNKNOWN_YEAR: "Kein Beitragsfeld für dieses Jahr",
    PlanStatus.ALREADY_APPLIED: "Bereits erledigt",
}


@dataclass(frozen=True)
class RunSummary:
    """Counts of one pipeline run."""

    seen: int
    already_applied: int
    newly_applied: int
    ambiguous: int
    unresolved: int
    unknown_year: int
    writes: int
    dry_run: bool

    @property
    def needs_attention(self) -> bool:
        """Whether this run has something the treasurer must see."""
        return bool(
            self.newly_applied or self.ambiguous or self.unresolved or self.unknown_year
        )

    @property
    def open_cases(self) -> int:
        """Returns the pipeline refused to write."""
        return self.ambiguous + self.unresolved + self.unknown_year


def summarize(plans: Sequence[ReturnPlan], *, dry_run: bool) -> RunSummary:
    """Count the outcomes of a run."""
    counts = {status: 0 for status in PlanStatus}
    for plan in plans:
        counts[plan.status] += 1

    return RunSummary(
        seen=len(plans),
        already_applied=counts[PlanStatus.ALREADY_APPLIED],
        newly_applied=counts[PlanStatus.APPLICABLE],
        ambiguous=counts[PlanStatus.AMBIGUOUS],
        unresolved=counts[PlanStatus.UNRESOLVED],
        unknown_year=counts[PlanStatus.UNKNOWN_YEAR],
        writes=sum(len(plan.writes) for plan in plans),
        dry_run=dry_run,
    )


def format_summary_line(summary: RunSummary) -> str:
    """One-line result, logged on every run."""
    return (
        f"{summary.seen} seen, "
        f"{summary.already_applied} already applied, "
        f"{summary.newly_applied} newly applied, "
        f"{summary.unresolved} unresolved, "
        f"{summary.ambiguous} ambiguous, "
        f"{summary.unknown_year} without Beitrag field"
    )


def format_report(plans: Sequence[ReturnPlan], summary: RunSummary) -> str:
    """Build the plain-text report body."""
    lines = [format_summary_line(summary)]
    if summary.dry_run:
        lines.append(DRY_RUN_NOTICE)

    for status in ATTENTION_STATUSES:
        section = [plan for plan in plans if plan.status is status]
        if not section:
            continue
        lines.extend(["", f"{SECTION_TITLES[status]} ({len(section)}):"])
        lines.extend(_format_plan(plan) for plan in section)

    return "\n".join(lines)


def build_subject(summary: RunSummary) -> str:
    """Build the mail subject."""
    return REPORT_SUBJECT.format(new=summary.newly_applied, open=summary.open_cases)


def send_report(config: ReportConfig, subject: str, body: str) -> None:
    """Mail the report to the treasurer."""
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = config.recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(config.smtp_host, config.smtp_port) as smtp:
        smtp.starttls()
        if config.smtp_user:
            smtp.login(config.smtp_user, config.smtp_password)
        smtp.send_message(message)


def _format_plan(plan: ReturnPlan) -> str:
    debit = plan.debit
    parts = [
        f"  {debit.mandate_reference or '(kein MREF)'}",
        f"{format_amount(debit.booked_amount)} €",
        debit.value_date.strftime(REPORT_DATE_FORMAT),
        f"Beitrag {debit.beitrag_year}",
    ]
    if debit.reason:
        parts.append(debit.reason)
    if plan.note:
        parts.append(plan.note)
    if not debit.amounts_reconcile:
        parts.append(f"Betrag unerwartet zusammengesetzt ({debit.own_bank_fee} €)")
    return " | ".join(parts)


def attention_plans(plans: Iterable[ReturnPlan]) -> list[ReturnPlan]:
    """Keep the plans a human has to look at."""
    return [plan for plan in plans if plan.status in ATTENTION_STATUSES]
