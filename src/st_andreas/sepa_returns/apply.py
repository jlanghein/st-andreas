"""Planning and execution of the Admidio writes a returned debit implies.

Planning is pure. Every write goes through an explicitly injected repository,
so no code path can reach a database that the caller did not hand over.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol

from st_andreas.admidio_db import ADMIDIO_SYSTEM_USER_ID, AdmidioField
from st_andreas.sepa_returns.match import (
    MandateMatch,
    MatchOutcome,
    MemberDirectory,
    MemberIdentity,
    build_directory,
    match_mandate,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    import pymysql

    from st_andreas.sepa_returns.detect import ReturnedDebit
    from st_andreas.sepa_returns.ledger import Ledger

BEITRAG_CHECKED: Final[str] = "1"
BEITRAG_CLEARED: Final[str] = "0"
BEITRAG_FIELD_PREFIX: Final[str] = "BEITRAG_"
BEITRAG_FIELD_SUFFIX: Final[str] = "_BEZAHLT"

VERMERK_TEMPLATE: Final[str] = "Lastschrift zurückgekommen ({amount} €, {date})"
GERMAN_DATE_FORMAT: Final[str] = "%d.%m.%Y"
VERMERK_LINE_SEPARATOR: Final[str] = "\n"
GERMAN_DECIMAL_SEPARATOR: Final[str] = ","
AMOUNT_QUANTUM: Final[Decimal] = Decimal("0.01")

USER_IS_VALID: Final[int] = 1

LOG_COMMENT_TEMPLATE: Final[str] = "Rücklastschrift {mandate} {date}"
LOG_COMMENT_MAX_LENGTH: Final[int] = 255

IDENTITY_FIELDS: Final[tuple[AdmidioField, ...]] = (
    AdmidioField.MITGLIEDSNR,
    AdmidioField.FAMILIENNR,
    AdmidioField.FIRST_NAME,
    AdmidioField.LAST_NAME,
)


class UnsupportedYearError(Exception):
    """Raised when Admidio has no ``Beitrag <year> bezahlt`` field."""

    def __init__(self, year: int) -> None:
        super().__init__(f"No Beitrag field defined for year {year}")
        self.year = year


class PlanStatus(StrEnum):
    """What the pipeline intends to do with one detected return."""

    APPLICABLE = "applicable"
    ALREADY_APPLIED = "already_applied"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    UNKNOWN_YEAR = "unknown_year"


class WriteOperation(StrEnum):
    """Whether a field value has to be inserted or updated."""

    INSERT = "insert"
    UPDATE = "update"


@dataclass(frozen=True)
class MemberFieldState:
    """The stored value of one user field, and the row that holds it."""

    usd_id: int | None
    value: str | None


@dataclass(frozen=True)
class FieldWrite:
    """A single pending change to ``adm_user_data``."""

    user_id: int
    field: AdmidioField
    operation: WriteOperation
    usd_id: int | None
    old_value: str | None
    new_value: str
    log_comment: str


@dataclass(frozen=True)
class UserLogRow:
    """One row of ``adm_user_log``, Admidio's own field-change history.

    The member history in Admidio's interface is built from this table, so a
    field change without one is a change nobody can trace back.
    """

    user_id: int
    field: AdmidioField
    old_value: str | None
    new_value: str
    created_by_user_id: int
    comment: str


@dataclass(frozen=True)
class ReturnPlan:
    """What one detected return leads to."""

    debit: ReturnedDebit
    match: MandateMatch
    status: PlanStatus
    writes: tuple[FieldWrite, ...]
    note: str

    @property
    def user_ids(self) -> tuple[int, ...]:
        """Users this plan writes to, in a stable order."""
        return tuple(dict.fromkeys(write.user_id for write in self.writes))


class MemberRepository(Protocol):
    """Read access to the Admidio user data a return has to be matched against."""

    def load_directory(self) -> MemberDirectory: ...

    def load_field_state(
        self, fields: Sequence[AdmidioField]
    ) -> Mapping[tuple[int, int], MemberFieldState]: ...


class ReturnWriter(Protocol):
    """Write access to a database the caller has explicitly authorised."""

    def apply(self, writes: Sequence[FieldWrite]) -> int: ...


def beitrag_fields() -> tuple[AdmidioField, ...]:
    """Every ``Beitrag <year> bezahlt`` field Admidio knows about."""
    return tuple(
        field
        for field in AdmidioField
        if field.name.startswith(BEITRAG_FIELD_PREFIX)
        and field.name.endswith(BEITRAG_FIELD_SUFFIX)
    )


def beitrag_field_for_year(year: int) -> AdmidioField:
    """Return the ``Beitrag <year> bezahlt`` field for a membership year."""
    try:
        return AdmidioField[f"{BEITRAG_FIELD_PREFIX}{year}{BEITRAG_FIELD_SUFFIX}"]
    except KeyError as error:
        raise UnsupportedYearError(year) from error


def format_amount(amount: Decimal) -> str:
    """Format an amount the way the hand-written Vermerk lines do."""
    return f"{amount.quantize(AMOUNT_QUANTUM)}".replace(".", GERMAN_DECIMAL_SEPARATOR)


def format_vermerk_line(debit: ReturnedDebit) -> str:
    """Build the Vermerk line for a returned debit."""
    return VERMERK_TEMPLATE.format(
        amount=format_amount(debit.booked_amount),
        date=debit.value_date.strftime(GERMAN_DATE_FORMAT),
    )


def format_log_comment(debit: ReturnedDebit) -> str:
    """Identify the return behind a change, for the Admidio history."""
    comment = LOG_COMMENT_TEMPLATE.format(
        mandate=debit.mandate_reference,
        date=debit.value_date.strftime(GERMAN_DATE_FORMAT),
    )
    return comment[:LOG_COMMENT_MAX_LENGTH]


def log_rows(writes: Iterable[FieldWrite]) -> list[UserLogRow]:
    """Build the history rows for a set of field writes, one per changed field."""
    return [
        UserLogRow(
            user_id=write.user_id,
            field=write.field,
            old_value=write.old_value,
            new_value=write.new_value,
            created_by_user_id=ADMIDIO_SYSTEM_USER_ID,
            comment=write.log_comment,
        )
        for write in writes
    ]


def plan_returns(
    debits: Iterable[ReturnedDebit],
    directory: MemberDirectory,
    field_state: Mapping[tuple[int, int], MemberFieldState],
    ledger: Ledger,
) -> list[ReturnPlan]:
    """Decide what to do with each detected return."""
    return [plan_return(debit, directory, field_state, ledger) for debit in debits]


def plan_return(
    debit: ReturnedDebit,
    directory: MemberDirectory,
    field_state: Mapping[tuple[int, int], MemberFieldState],
    ledger: Ledger,
) -> ReturnPlan:
    """Decide what to do with one detected return."""
    match = match_mandate(directory, debit.mandate_reference)

    if ledger.contains(debit.fingerprint):
        return ReturnPlan(
            debit=debit,
            match=match,
            status=PlanStatus.ALREADY_APPLIED,
            writes=(),
            note="Recorded in the ledger",
        )

    if not match.is_writable:
        return ReturnPlan(
            debit=debit,
            match=match,
            status=_unwritable_status(match),
            writes=(),
            note=match.detail,
        )

    try:
        beitrag_field = beitrag_field_for_year(debit.beitrag_year)
    except UnsupportedYearError as error:
        return ReturnPlan(
            debit=debit,
            match=match,
            status=PlanStatus.UNKNOWN_YEAR,
            writes=(),
            note=str(error),
        )

    writes = tuple(
        write
        for member in match.members
        for write in _member_writes(member, debit, beitrag_field, field_state)
    )
    if not writes:
        return ReturnPlan(
            debit=debit,
            match=match,
            status=PlanStatus.ALREADY_APPLIED,
            writes=(),
            note=f"{beitrag_field.name} is already cleared",
        )

    return ReturnPlan(
        debit=debit,
        match=match,
        status=PlanStatus.APPLICABLE,
        writes=writes,
        note=match.detail,
    )


def applicable_plans(plans: Iterable[ReturnPlan]) -> list[ReturnPlan]:
    """Keep only the plans that carry pending writes."""
    return [plan for plan in plans if plan.status is PlanStatus.APPLICABLE]


@dataclass(frozen=True)
class AdmidioRepository:
    """Reads and writes against one explicitly supplied Admidio connection."""

    connection: pymysql.Connection
    table_prefix: str

    def load_directory(self) -> MemberDirectory:
        """Index every non-deleted user, including members who have left."""
        placeholders = ",".join(["%s"] * len(IDENTITY_FIELDS))
        query = f"""
            SELECT ud.usd_usr_id, uf.usf_name_intern, ud.usd_value
            FROM {self.table_prefix}user_data ud
            JOIN {self.table_prefix}users u ON ud.usd_usr_id = u.usr_id
            JOIN {self.table_prefix}user_fields uf ON ud.usd_usf_id = uf.usf_id
            WHERE uf.usf_id IN ({placeholders})
              AND u.usr_valid = %s
        """
        params = (*(field.value for field in IDENTITY_FIELDS), USER_IS_VALID)

        with self.connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()

        by_user: dict[int, dict[str, str]] = {}
        for row in rows:
            values = by_user.setdefault(row["usd_usr_id"], {})
            values[row["usf_name_intern"]] = row["usd_value"] or ""

        return build_directory(
            MemberIdentity(
                user_id=user_id,
                mitglieds_nr=values.get(AdmidioField.MITGLIEDSNR.name, ""),
                familien_nr=values.get(AdmidioField.FAMILIENNR.name) or None,
                first_name=values.get(AdmidioField.FIRST_NAME.name, ""),
                last_name=values.get(AdmidioField.LAST_NAME.name, ""),
            )
            for user_id, values in by_user.items()
        )

    def load_field_state(
        self, fields: Sequence[AdmidioField]
    ) -> Mapping[tuple[int, int], MemberFieldState]:
        """Read the current value of the given fields for every user."""
        placeholders = ",".join(["%s"] * len(fields))
        query = f"""
            SELECT ud.usd_id, ud.usd_usr_id, ud.usd_usf_id, ud.usd_value
            FROM {self.table_prefix}user_data ud
            WHERE ud.usd_usf_id IN ({placeholders})
        """

        with self.connection.cursor() as cursor:
            cursor.execute(query, tuple(field.value for field in fields))
            rows = cursor.fetchall()

        return {
            (row["usd_usr_id"], row["usd_usf_id"]): MemberFieldState(
                usd_id=row["usd_id"],
                value=row["usd_value"],
            )
            for row in rows
        }

    def apply(self, writes: Sequence[FieldWrite]) -> int:
        """Execute all writes and their history rows in a single transaction."""
        update = f"""
            UPDATE {self.table_prefix}user_data
            SET usd_value = %s
            WHERE usd_id = %s
        """
        insert = f"""
            INSERT INTO {self.table_prefix}user_data
                (usd_usr_id, usd_usf_id, usd_value)
            VALUES (%s, %s, %s)
        """
        log = f"""
            INSERT INTO {self.table_prefix}user_log
                (usl_usr_id, usl_usf_id, usl_value_old, usl_value_new,
                 usl_usr_id_create, usl_comment)
            VALUES (%s, %s, %s, %s, %s, %s)
        """

        with self.connection.cursor() as cursor:
            for write in writes:
                if write.operation is WriteOperation.UPDATE:
                    cursor.execute(update, (write.new_value, write.usd_id))
                else:
                    cursor.execute(
                        insert, (write.user_id, write.field.value, write.new_value)
                    )

            for row in log_rows(writes):
                cursor.execute(
                    log,
                    (
                        row.user_id,
                        row.field.value,
                        row.old_value,
                        row.new_value,
                        row.created_by_user_id,
                        row.comment,
                    ),
                )

        self.connection.commit()
        return len(writes)


def _unwritable_status(match: MandateMatch) -> PlanStatus:
    if match.outcome is MatchOutcome.UNRESOLVED:
        return PlanStatus.UNRESOLVED
    return PlanStatus.AMBIGUOUS


def _member_writes(
    member: MemberIdentity,
    debit: ReturnedDebit,
    beitrag_field: AdmidioField,
    field_state: Mapping[tuple[int, int], MemberFieldState],
) -> list[FieldWrite]:
    """Build the writes for one member, guarding every one of them.

    The Vermerk is only appended together with clearing the checkbox: a
    cleared checkbox means the return was already reconciled, by this pipeline
    or by hand, and a second note would be noise.
    """
    checkbox = field_state.get((member.user_id, beitrag_field.value))
    if checkbox is None or checkbox.value != BEITRAG_CHECKED:
        return []

    writes = [
        FieldWrite(
            user_id=member.user_id,
            field=beitrag_field,
            operation=WriteOperation.UPDATE,
            usd_id=checkbox.usd_id,
            old_value=checkbox.value,
            new_value=BEITRAG_CLEARED,
            log_comment=format_log_comment(debit),
        )
    ]

    vermerk_write = _vermerk_write(member, debit, field_state)
    if vermerk_write is not None:
        writes.append(vermerk_write)

    return writes


def _vermerk_write(
    member: MemberIdentity,
    debit: ReturnedDebit,
    field_state: Mapping[tuple[int, int], MemberFieldState],
) -> FieldWrite | None:
    line = format_vermerk_line(debit)
    state = field_state.get((member.user_id, AdmidioField.VERMERK.value))
    existing = (state.value if state else None) or ""

    if line in existing:
        return None

    appended = f"{existing}{VERMERK_LINE_SEPARATOR}{line}" if existing else line
    operation = (
        WriteOperation.UPDATE
        if state is not None and state.usd_id is not None
        else WriteOperation.INSERT
    )

    return FieldWrite(
        user_id=member.user_id,
        field=AdmidioField.VERMERK,
        operation=operation,
        usd_id=state.usd_id if state else None,
        old_value=state.value if state else None,
        new_value=appended,
        log_comment=format_log_comment(debit),
    )
