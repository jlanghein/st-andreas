"""Tests for planning the Admidio writes a return implies."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from st_andreas.admidio_db import AdmidioField
from st_andreas.member_pipeline.pipeline import ADMIDIO_SYSTEM_USER_ID as SYSTEM_USER
from st_andreas.sepa_returns.apply import (
    ADMIDIO_SYSTEM_USER_ID,
    BEITRAG_CHECKED,
    BEITRAG_CLEARED,
    LOG_COMMENT_MAX_LENGTH,
    MemberFieldState,
    PlanStatus,
    UnsupportedYearError,
    WriteOperation,
    beitrag_field_for_year,
    beitrag_fields,
    format_amount,
    format_log_comment,
    format_vermerk_line,
    log_rows,
    plan_return,
    plan_returns,
)
from st_andreas.sepa_returns.detect import ReturnedDebit
from st_andreas.sepa_returns.ledger import EMPTY_LEDGER, build_record
from st_andreas.sepa_returns.match import MemberIdentity, build_directory

MEMBER = MemberIdentity(
    user_id=1,
    mitglieds_nr="XY123456",
    familien_nr=None,
    first_name="Erika",
    last_name="Müller",
)
FAMILY = (
    MemberIdentity(
        user_id=2,
        mitglieds_nr="FB000001",
        familien_nr="FA0042F",
        first_name="Max",
        last_name="Beispiel",
    ),
    MemberIdentity(
        user_id=3,
        mitglieds_nr="FB000002",
        familien_nr="FA0042F",
        first_name="Mia",
        last_name="Beispiel",
    ),
)
DUPLICATES = (
    MemberIdentity(
        user_id=4,
        mitglieds_nr="DUP00001",
        familien_nr=None,
        first_name="Anna",
        last_name="Eins",
    ),
    MemberIdentity(
        user_id=5,
        mitglieds_nr="DUP00001",
        familien_nr=None,
        first_name="Bert",
        last_name="Zwei",
    ),
)

DIRECTORY = build_directory([MEMBER, *FAMILY, *DUPLICATES])

BEITRAG_2026 = AdmidioField.BEITRAG_2026_BEZAHLT.value
VERMERK = AdmidioField.VERMERK.value
EXPECTED_VERMERK = "Lastschrift zurückgekommen (128,11 €, 13.05.2026)"
EXPECTED_LOG_COMMENT = "Rücklastschrift XY123456 13.05.2026"


def build_debit(
    mandate_reference: str = "XY123456",
    booked_amount: Decimal = Decimal("128.11"),
    beitrag_year: int = 2026,
) -> ReturnedDebit:
    return ReturnedDebit(
        account="50010517/1234567",
        value_date=date(2026, 5, 13),
        entry_date=date(2026, 5, 13),
        booked_amount=booked_amount,
        mandate_reference=mandate_reference,
        end_to_end_reference="NOTPROVIDED",
        original_amount=Decimal("120.00"),
        debtor_bank_fee=Decimal("3.00"),
        reason="SONSTIGE GRUENDE",
        beitrag_year=beitrag_year,
        booking_text="SEPA-LASTSCHR. RETOURE CORE",
        counterparty_name="Erika Müller",
    )


def checkbox_state(
    user_id: int, value: str = BEITRAG_CHECKED
) -> dict[tuple[int, int], MemberFieldState]:
    return {(user_id, BEITRAG_2026): MemberFieldState(usd_id=user_id * 10, value=value)}


class TestBeitragField:
    def test_maps_a_year_to_its_field(self) -> None:
        assert beitrag_field_for_year(2026) is AdmidioField.BEITRAG_2026_BEZAHLT

    def test_maps_the_previous_year(self) -> None:
        assert beitrag_field_for_year(2025) is AdmidioField.BEITRAG_2025_BEZAHLT

    def test_rejects_a_year_without_a_field(self) -> None:
        with pytest.raises(UnsupportedYearError):
            beitrag_field_for_year(2027)

    def test_lists_every_known_beitrag_field(self) -> None:
        assert set(beitrag_fields()) == {
            AdmidioField.BEITRAG_2025_BEZAHLT,
            AdmidioField.BEITRAG_2026_BEZAHLT,
        }


class TestFormatting:
    def test_formats_an_amount_with_a_decimal_comma(self) -> None:
        assert format_amount(Decimal("128.11")) == "128,11"

    def test_pads_to_two_decimals(self) -> None:
        assert format_amount(Decimal("120")) == "120,00"

    def test_builds_the_established_vermerk_line(self) -> None:
        assert format_vermerk_line(build_debit()) == EXPECTED_VERMERK

    def test_log_comment_identifies_the_return(self) -> None:
        assert format_log_comment(build_debit()) == EXPECTED_LOG_COMMENT

    def test_log_comment_fits_the_column(self) -> None:
        comment = format_log_comment(build_debit(mandate_reference="X" * 400))

        assert len(comment) <= LOG_COMMENT_MAX_LENGTH


class TestPlanReturn:
    def test_clears_the_checkbox_and_appends_a_vermerk(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        assert plan.status is PlanStatus.APPLICABLE
        assert [write.field for write in plan.writes] == [
            AdmidioField.BEITRAG_2026_BEZAHLT,
            AdmidioField.VERMERK,
        ]

    def test_clears_the_checkbox_to_zero(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        assert plan.writes[0].new_value == BEITRAG_CLEARED
        assert plan.writes[0].operation is WriteOperation.UPDATE

    def test_inserts_a_vermerk_when_the_member_has_none(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        assert plan.writes[1].operation is WriteOperation.INSERT
        assert plan.writes[1].new_value == EXPECTED_VERMERK

    def test_appends_to_an_existing_vermerk(self) -> None:
        state = checkbox_state(1) | {
            (1, VERMERK): MemberFieldState(usd_id=99, value="Zahlt per Überweisung")
        }

        plan = plan_return(build_debit(), DIRECTORY, state, EMPTY_LEDGER)

        assert plan.writes[1].operation is WriteOperation.UPDATE
        assert plan.writes[1].new_value == f"Zahlt per Überweisung\n{EXPECTED_VERMERK}"

    def test_does_not_repeat_an_existing_vermerk_line(self) -> None:
        state = checkbox_state(1) | {
            (1, VERMERK): MemberFieldState(usd_id=99, value=EXPECTED_VERMERK)
        }

        plan = plan_return(build_debit(), DIRECTORY, state, EMPTY_LEDGER)

        assert [write.field for write in plan.writes] == [
            AdmidioField.BEITRAG_2026_BEZAHLT
        ]

    def test_writes_for_every_member_of_a_family(self) -> None:
        state = checkbox_state(2) | checkbox_state(3)

        plan = plan_return(build_debit("FA0042F"), DIRECTORY, state, EMPTY_LEDGER)

        assert plan.user_ids == (2, 3)

    def test_a_cleared_checkbox_counts_as_already_applied(self) -> None:
        plan = plan_return(
            build_debit(),
            DIRECTORY,
            checkbox_state(1, BEITRAG_CLEARED),
            EMPTY_LEDGER,
        )

        assert plan.status is PlanStatus.ALREADY_APPLIED
        assert plan.writes == ()

    def test_a_member_without_the_field_is_not_written(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, {}, EMPTY_LEDGER)

        assert plan.status is PlanStatus.ALREADY_APPLIED
        assert plan.writes == ()

    def test_a_ledger_entry_short_circuits_the_plan(self) -> None:
        debit = build_debit()
        ledger = EMPTY_LEDGER.extended([build_record(debit, [1])])

        plan = plan_return(debit, DIRECTORY, checkbox_state(1), ledger)

        assert plan.status is PlanStatus.ALREADY_APPLIED
        assert plan.writes == ()

    def test_an_ambiguous_reference_is_never_written(self) -> None:
        state = checkbox_state(4) | checkbox_state(5)

        plan = plan_return(build_debit("DUP00001"), DIRECTORY, state, EMPTY_LEDGER)

        assert plan.status is PlanStatus.AMBIGUOUS
        assert plan.writes == ()

    def test_an_unknown_reference_is_never_written(self) -> None:
        plan = plan_return(
            build_debit("ZZ999999"), DIRECTORY, checkbox_state(1), EMPTY_LEDGER
        )

        assert plan.status is PlanStatus.UNRESOLVED
        assert plan.writes == ()

    def test_a_year_without_a_field_is_never_written(self) -> None:
        plan = plan_return(
            build_debit(beitrag_year=2027), DIRECTORY, checkbox_state(1), EMPTY_LEDGER
        )

        assert plan.status is PlanStatus.UNKNOWN_YEAR
        assert plan.writes == ()


class TestPlanReturns:
    def test_plans_every_return(self) -> None:
        debits = [build_debit(), build_debit("ZZ999999")]

        plans = plan_returns(debits, DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        assert [plan.status for plan in plans] == [
            PlanStatus.APPLICABLE,
            PlanStatus.UNRESOLVED,
        ]


class TestLogRows:
    def test_one_row_per_changed_field(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        rows = log_rows(plan.writes)

        assert [row.field for row in rows] == [
            AdmidioField.BEITRAG_2026_BEZAHLT,
            AdmidioField.VERMERK,
        ]

    def test_carries_the_old_and_new_value(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        checkbox_row = log_rows(plan.writes)[0]

        assert (checkbox_row.old_value, checkbox_row.new_value) == (
            BEITRAG_CHECKED,
            BEITRAG_CLEARED,
        )

    def test_a_field_without_a_previous_row_logs_no_old_value(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        vermerk_row = log_rows(plan.writes)[1]

        assert vermerk_row.old_value is None
        assert vermerk_row.new_value == EXPECTED_VERMERK

    def test_keeps_the_previous_vermerk_as_the_old_value(self) -> None:
        state = checkbox_state(1) | {
            (1, VERMERK): MemberFieldState(usd_id=99, value="Zahlt per Überweisung")
        }
        plan = plan_return(build_debit(), DIRECTORY, state, EMPTY_LEDGER)

        assert log_rows(plan.writes)[1].old_value == "Zahlt per Überweisung"

    def test_the_system_account_is_the_actor(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        assert all(
            row.created_by_user_id == ADMIDIO_SYSTEM_USER_ID
            for row in log_rows(plan.writes)
        )

    def test_the_actor_is_the_same_one_the_upload_pipeline_uses(self) -> None:
        assert ADMIDIO_SYSTEM_USER_ID == SYSTEM_USER

    def test_every_row_names_the_return(self) -> None:
        plan = plan_return(build_debit(), DIRECTORY, checkbox_state(1), EMPTY_LEDGER)

        assert all(row.comment == EXPECTED_LOG_COMMENT for row in log_rows(plan.writes))

    def test_a_skipped_write_leaves_no_history(self) -> None:
        plan = plan_return(
            build_debit(), DIRECTORY, checkbox_state(1, BEITRAG_CLEARED), EMPTY_LEDGER
        )

        assert log_rows(plan.writes) == []
