"""End-to-end tests of one pipeline run, from export file to planned writes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest
from aioclock import At

from st_andreas.admidio_db import AdmidioField
from st_andreas.pipelines.sepa_returns import (
    TargetMismatchError,
    create_scheduler,
    resolve_write_target,
)
from st_andreas.sepa_returns.apply import (
    BEITRAG_CHECKED,
    FieldWrite,
    MemberFieldState,
    PlanStatus,
)
from st_andreas.sepa_returns.config import (
    AccountConfig,
    ReturnsConfig,
    ScheduleConfig,
)
from st_andreas.sepa_returns.match import (
    MemberDirectory,
    MemberIdentity,
    build_directory,
)
from st_andreas.sepa_returns.runner import AccountMismatchError, RunRequest, run_once
from st_andreas.sepa_returns.share import LocalDirectorySource, ShareError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mt940"
FOREIGN_DIR = FIXTURE_DIR / "foreign"

ACCOUNT = AccountConfig(account_number="1234567", bank_code="50010517")
BEITRAG_2026 = AdmidioField.BEITRAG_2026_BEZAHLT.value

MEMBERS = (
    MemberIdentity(
        user_id=1,
        mitglieds_nr="XY123456",
        familien_nr=None,
        first_name="Erika",
        last_name="Müller",
    ),
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
    MemberIdentity(
        user_id=5,
        mitglieds_nr="AB010203",
        familien_nr=None,
        first_name="Dora",
        last_name="Doppelt",
    ),
    MemberIdentity(
        user_id=6,
        mitglieds_nr="CD040506",
        familien_nr="AB010203",
        first_name="Nils",
        last_name="Namensvetter",
    ),
)

FIRST_INSERTED_ROW_ID = 1000


@dataclass
class FakeRepository:
    """In-memory stand-in for the Admidio database."""

    directory: MemberDirectory
    state: dict[tuple[int, int], MemberFieldState]
    applied: list[FieldWrite] = field(default_factory=list)
    next_row_id: int = FIRST_INSERTED_ROW_ID

    def load_directory(self) -> MemberDirectory:
        return self.directory

    def load_field_state(
        self, fields: Sequence[AdmidioField]
    ) -> dict[tuple[int, int], MemberFieldState]:
        wanted = {field_.value for field_ in fields}
        return {key: value for key, value in self.state.items() if key[1] in wanted}

    def apply(self, writes: Sequence[FieldWrite]) -> int:
        for write in writes:
            usd_id = write.usd_id
            if usd_id is None:
                usd_id = self.next_row_id
                self.next_row_id += 1
            self.state[(write.user_id, write.field.value)] = MemberFieldState(
                usd_id=usd_id, value=write.new_value
            )
        self.applied.extend(writes)
        return len(writes)


def build_repository(
    paid_user_ids: tuple[int, ...] = (1, 2, 3, 5, 6),
) -> FakeRepository:
    return FakeRepository(
        directory=build_directory(MEMBERS),
        state={
            (user_id, BEITRAG_2026): MemberFieldState(
                usd_id=user_id * 10, value=BEITRAG_CHECKED
            )
            for user_id in paid_user_ids
        },
    )


def build_request(
    repository: FakeRepository,
    ledger_path: Path,
    *,
    write: bool = False,
    since: date | None = None,
    directory: Path = FIXTURE_DIR,
) -> RunRequest:
    return RunRequest(
        source=LocalDirectorySource(directory=directory),
        account=ACCOUNT,
        repository=repository,
        ledger_path=ledger_path,
        writer=repository if write else None,
        since=since,
    )


class TestDryRun:
    def test_reads_the_newest_rolling_window_export(self, tmp_path: Path) -> None:
        repository = build_repository()

        result = run_once(build_request(repository, tmp_path / "ledger.json"))

        assert result.export.name == "STA_1234567_50010517_20260902_060512.sta"

    def test_classifies_every_return(self, tmp_path: Path) -> None:
        repository = build_repository()

        result = run_once(build_request(repository, tmp_path / "ledger.json"))

        assert [plan.status for plan in result.plans] == [
            PlanStatus.APPLICABLE,
            PlanStatus.APPLICABLE,
            PlanStatus.UNRESOLVED,
            PlanStatus.AMBIGUOUS,
        ]

    def test_counts_the_run(self, tmp_path: Path) -> None:
        repository = build_repository()

        summary = run_once(build_request(repository, tmp_path / "ledger.json")).summary

        assert (summary.seen, summary.newly_applied) == (4, 2)
        assert (summary.unresolved, summary.ambiguous) == (1, 1)
        assert summary.dry_run

    def test_writes_nothing(self, tmp_path: Path) -> None:
        repository = build_repository()
        ledger_path = tmp_path / "ledger.json"
        before = dict(repository.state)

        run_once(build_request(repository, ledger_path))

        assert repository.applied == []
        assert repository.state == before
        assert not ledger_path.exists()

    def test_resolves_a_family_return_to_every_member(self, tmp_path: Path) -> None:
        repository = build_repository()

        result = run_once(build_request(repository, tmp_path / "ledger.json"))

        assert result.plans[1].user_ids == (2, 3)

    def test_reports_a_member_who_cannot_be_found(self, tmp_path: Path) -> None:
        repository = build_repository()

        result = run_once(build_request(repository, tmp_path / "ledger.json"))

        assert result.plans[2].debit.mandate_reference == "ZZ999999"
        assert result.plans[2].writes == ()


class TestApplyRun:
    def test_clears_the_checkbox_of_every_matched_member(self, tmp_path: Path) -> None:
        repository = build_repository()

        run_once(build_request(repository, tmp_path / "ledger.json", write=True))

        assert [repository.state[(user, BEITRAG_2026)].value for user in (1, 2, 3)] == [
            "0",
            "0",
            "0",
        ]

    def test_leaves_ambiguous_members_untouched(self, tmp_path: Path) -> None:
        repository = build_repository()

        run_once(build_request(repository, tmp_path / "ledger.json", write=True))

        assert repository.state[(5, BEITRAG_2026)].value == BEITRAG_CHECKED
        assert repository.state[(6, BEITRAG_2026)].value == BEITRAG_CHECKED

    def test_appends_the_vermerk(self, tmp_path: Path) -> None:
        repository = build_repository()

        run_once(build_request(repository, tmp_path / "ledger.json", write=True))

        vermerk = repository.state[(1, AdmidioField.VERMERK.value)]
        assert vermerk.value == "Lastschrift zurückgekommen (128,11 €, 13.05.2026)"

    def test_records_the_applied_returns_in_the_ledger(self, tmp_path: Path) -> None:
        repository = build_repository()
        ledger_path = tmp_path / "ledger.json"

        run_once(build_request(repository, ledger_path, write=True))

        assert ledger_path.exists()

    def test_a_second_run_changes_nothing(self, tmp_path: Path) -> None:
        repository = build_repository()
        ledger_path = tmp_path / "ledger.json"
        run_once(build_request(repository, ledger_path, write=True))
        repository.applied.clear()

        summary = run_once(build_request(repository, ledger_path, write=True)).summary

        assert repository.applied == []
        assert (summary.seen, summary.already_applied, summary.newly_applied) == (
            4,
            2,
            0,
        )

    def test_a_hand_reconciled_return_is_left_alone(self, tmp_path: Path) -> None:
        # No ledger at all: the cleared checkbox alone has to stop the write.
        repository = build_repository(paid_user_ids=(5, 6))

        result = run_once(
            build_request(repository, tmp_path / "ledger.json", write=True)
        )

        assert repository.applied == []
        assert result.summary.already_applied == 2


class TestSince:
    def test_ignores_returns_before_the_cutoff(self, tmp_path: Path) -> None:
        repository = build_repository()

        result = run_once(
            build_request(repository, tmp_path / "ledger.json", since=date(2026, 6, 1))
        )

        assert [plan.debit.mandate_reference for plan in result.plans] == [
            "ZZ999999",
            "AB010203",
        ]


class TestGuards:
    def test_refuses_a_statement_for_another_account(self, tmp_path: Path) -> None:
        repository = build_repository()

        with pytest.raises(AccountMismatchError):
            run_once(
                build_request(
                    repository, tmp_path / "ledger.json", directory=FOREIGN_DIR
                )
            )

    def test_reports_a_missing_export(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        repository = build_repository()

        with pytest.raises(ShareError):
            run_once(
                build_request(repository, tmp_path / "ledger.json", directory=empty)
            )


class TestResolveWriteTarget:
    def test_no_target_means_dry_run(self) -> None:
        assert resolve_write_target(None, "admidio") is None

    def test_the_configured_database_is_accepted(self) -> None:
        assert resolve_write_target("admidio", "admidio") == "admidio"

    def test_another_database_is_refused(self) -> None:
        with pytest.raises(TargetMismatchError):
            resolve_write_target("production", "admidio")


class TestScheduler:
    def test_schedules_the_import_weekly(self, tmp_path: Path) -> None:
        config = ReturnsConfig(
            account=ACCOUNT,
            share=None,
            report=None,
            schedule=ScheduleConfig(hour=6, minute=30, timezone="Europe/Berlin"),
            ledger_path=tmp_path / "ledger.json",
        )

        app = create_scheduler(
            config,
            LocalDirectorySource(directory=FIXTURE_DIR),
            table_prefix="adm_",
            write_target=None,
            since=None,
        )

        assert app._app_tasks[0].trigger == At(
            tz="Europe/Berlin", at="every monday", hour=6, minute=30, second=0
        )
