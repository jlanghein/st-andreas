"""One run of the returns pipeline, from export file to Admidio writes.

The database is reached only through the repository and writer handed in by
the caller; a run without a writer cannot write anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from st_andreas.admidio_db import AdmidioField
from st_andreas.sepa_returns.apply import (
    applicable_plans,
    beitrag_fields,
    plan_returns,
)
from st_andreas.sepa_returns.detect import detect_returns, returns_since
from st_andreas.sepa_returns.ledger import build_record, load_ledger, save_ledger
from st_andreas.sepa_returns.mt940 import decode_statements, parse_statements
from st_andreas.sepa_returns.report import RunSummary, summarize
from st_andreas.sepa_returns.share import ShareError, StatementExport, select_export

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from pathlib import Path

    from st_andreas.sepa_returns.apply import (
        MemberRepository,
        ReturnPlan,
        ReturnWriter,
    )
    from st_andreas.sepa_returns.config import AccountConfig
    from st_andreas.sepa_returns.ledger import Ledger
    from st_andreas.sepa_returns.mt940 import Statement
    from st_andreas.sepa_returns.share import StatementSource


class AccountMismatchError(Exception):
    """Raised when an export holds statements for a different account."""

    def __init__(self, expected: str, found: Sequence[str]) -> None:
        super().__init__(
            f"Export holds statements for {', '.join(found)}, expected {expected}"
        )
        self.expected = expected
        self.found = tuple(found)


@dataclass(frozen=True)
class RunRequest:
    """Everything one run needs, including its database access."""

    source: StatementSource
    account: AccountConfig
    repository: MemberRepository
    ledger_path: Path
    writer: ReturnWriter | None = None
    since: date | None = None


@dataclass(frozen=True)
class RunResult:
    """The outcome of one run."""

    export: StatementExport
    plans: tuple[ReturnPlan, ...]
    summary: RunSummary


def run_once(request: RunRequest) -> RunResult:
    """Import the newest export and reconcile the returns it contains."""
    export = select_export(request.source.list_names(), request.account.account_number)
    if export is None:
        raise ShareError(
            f"No {request.account.account_number} export found on the share"
        )

    statements = parse_statements(decode_statements(request.source.read(export.name)))
    _verify_account(statements, request.account.statement_identifier)

    debits = detect_returns(statements)
    if request.since is not None:
        debits = returns_since(debits, request.since)

    ledger = load_ledger(request.ledger_path)
    plans = plan_returns(
        debits,
        request.repository.load_directory(),
        request.repository.load_field_state([AdmidioField.VERMERK, *beitrag_fields()]),
        ledger,
    )

    if request.writer is not None:
        _apply(request.writer, request.ledger_path, ledger, plans)

    return RunResult(
        export=export,
        plans=tuple(plans),
        summary=summarize(plans, dry_run=request.writer is None),
    )


def _verify_account(statements: Sequence[Statement], expected: str) -> None:
    foreign = sorted(
        {statement.account for statement in statements if statement.account != expected}
    )
    if foreign:
        raise AccountMismatchError(expected, foreign)


def _apply(
    writer: ReturnWriter,
    ledger_path: Path,
    ledger: Ledger,
    plans: Sequence[ReturnPlan],
) -> None:
    pending = applicable_plans(plans)
    if not pending:
        return

    writer.apply([write for plan in pending for write in plan.writes])

    records = [build_record(plan.debit, plan.user_ids) for plan in pending]
    save_ledger(ledger_path, ledger.extended(records))
