"""Tests for the run summary and its report body."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from st_andreas.sepa_returns.apply import PlanStatus, ReturnPlan
from st_andreas.sepa_returns.detect import ReturnedDebit
from st_andreas.sepa_returns.match import MandateMatch, MatchOutcome
from st_andreas.sepa_returns.report import (
    build_subject,
    format_report,
    format_summary_line,
    summarize,
)


def build_debit(mandate_reference: str = "XY123456") -> ReturnedDebit:
    return ReturnedDebit(
        account="50010517/1234567",
        value_date=date(2026, 5, 13),
        entry_date=date(2026, 5, 13),
        booked_amount=Decimal("128.11"),
        mandate_reference=mandate_reference,
        end_to_end_reference="NOTPROVIDED",
        original_amount=Decimal("120.00"),
        debtor_bank_fee=Decimal("3.00"),
        reason="WIDERSPRUCH DURCH ZAHLER",
        beitrag_year=2026,
        booking_text="SEPA-LASTSCHR. RETOURE CORE",
        counterparty_name="Erika Müller",
    )


def build_plan(status: PlanStatus, mandate_reference: str = "XY123456") -> ReturnPlan:
    return ReturnPlan(
        debit=build_debit(mandate_reference),
        match=MandateMatch(
            mandate_reference=mandate_reference,
            outcome=MatchOutcome.RESOLVED,
            members=(),
            detail="Erika Müller (#1)",
        ),
        status=status,
        writes=(),
        note="Erika Müller (#1)",
    )


class TestSummarize:
    def test_counts_each_status(self) -> None:
        plans = [
            build_plan(PlanStatus.APPLICABLE),
            build_plan(PlanStatus.ALREADY_APPLIED),
            build_plan(PlanStatus.UNRESOLVED),
            build_plan(PlanStatus.AMBIGUOUS),
            build_plan(PlanStatus.UNKNOWN_YEAR),
        ]

        summary = summarize(plans, dry_run=False)

        assert summary.seen == 5
        assert summary.newly_applied == 1
        assert summary.already_applied == 1
        assert summary.unresolved == 1
        assert summary.ambiguous == 1
        assert summary.unknown_year == 1

    def test_a_run_with_nothing_new_needs_no_attention(self) -> None:
        summary = summarize([build_plan(PlanStatus.ALREADY_APPLIED)], dry_run=False)

        assert not summary.needs_attention

    def test_an_unresolved_return_needs_attention(self) -> None:
        summary = summarize([build_plan(PlanStatus.UNRESOLVED)], dry_run=False)

        assert summary.needs_attention
        assert summary.open_cases == 1

    def test_an_empty_run_needs_no_attention(self) -> None:
        assert not summarize([], dry_run=True).needs_attention


class TestFormatting:
    def test_summary_line_names_every_count(self) -> None:
        summary = summarize([build_plan(PlanStatus.APPLICABLE)], dry_run=False)

        assert format_summary_line(summary) == (
            "1 seen, 0 already applied, 1 newly applied, 0 unresolved, "
            "0 ambiguous, 0 without Beitrag field"
        )

    def test_report_lists_the_open_cases(self) -> None:
        plans = [
            build_plan(PlanStatus.UNRESOLVED, "ZZ999999"),
            build_plan(PlanStatus.ALREADY_APPLIED, "XY123456"),
        ]

        body = format_report(plans, summarize(plans, dry_run=True))

        assert "ZZ999999" in body
        assert "XY123456" not in body

    def test_report_marks_a_dry_run(self) -> None:
        plans = [build_plan(PlanStatus.APPLICABLE)]

        body = format_report(plans, summarize(plans, dry_run=True))

        assert "Dry run" in body

    def test_subject_carries_the_counts(self) -> None:
        plans = [
            build_plan(PlanStatus.APPLICABLE),
            build_plan(PlanStatus.UNRESOLVED),
        ]

        subject = build_subject(summarize(plans, dry_run=False))

        assert subject == "SEPA-Rücklastschriften: 1 neu, 1 offen"
