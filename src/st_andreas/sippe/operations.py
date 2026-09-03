"""Core SIPPE database operations.

This module provides the database operations for SIPPE management.
All operations are pure functions that take a connection and return results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from st_andreas.admidio_db import (
    MEMBERS_ROLE_NAME,
    PERMANENT_MEMBERSHIP_END,
    USER_IS_VALID,
    AdmidioField,
)

if TYPE_CHECKING:
    import pymysql


SIPPE_FIELD_ID: Final[int] = AdmidioField.SIPPE.value


@dataclass(frozen=True)
class SippeInfo:
    """Information about a single Sippe."""

    name: str
    position: int
    member_count: int


@dataclass(frozen=True)
class MemberSippe:
    """A member's Sippe assignment."""

    user_id: int
    usd_id: int
    position: int
    sippe_name: str


@dataclass(frozen=True)
class SippeState:
    """Current state of Sippe data in the database."""

    sippe_list: list[SippeInfo]
    members: list[MemberSippe]


@dataclass(frozen=True)
class MutationPlan:
    """Plan for a Sippe mutation operation."""

    new_sippe_names: list[str]
    member_updates: list[tuple[MemberSippe, int]]
    description: str


class SippeNotFoundError(Exception):
    """Raised when a Sippe name is not found."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Sippe not found: {name}")
        self.name = name


class SippeAlreadyExistsError(Exception):
    """Raised when trying to add a Sippe that already exists."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Sippe already exists: {name}")
        self.name = name


class SippeHasMembersError(Exception):
    """Raised when trying to delete a Sippe that has members without reassignment."""

    def __init__(self, name: str, member_count: int) -> None:
        super().__init__(
            f"Sippe '{name}' has {member_count} members. "
            f"Use --reassign-to to reassign them first."
        )
        self.name = name
        self.member_count = member_count


def fetch_sippe_names(
    conn: pymysql.Connection,
    table_prefix: str,
) -> list[str]:
    """Fetch the raw Sippe value list from the database."""
    query = f"""
        SELECT usf_value_list 
        FROM {table_prefix}user_fields 
        WHERE usf_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(query, (SIPPE_FIELD_ID,))
        result = cursor.fetchone()

    if not result or not result["usf_value_list"]:
        return []

    raw_value = result["usf_value_list"]
    return [name.strip() for name in raw_value.replace("\r\n", "\n").split("\n")]


def fetch_member_assignments(
    conn: pymysql.Connection,
    table_prefix: str,
    sippe_names: list[str],
) -> list[MemberSippe]:
    """Fetch all members with their Sippe assignments."""
    query = f"""
        SELECT 
            ud.usd_id,
            ud.usd_usr_id,
            ud.usd_value
        FROM {table_prefix}user_data ud
        JOIN {table_prefix}users u ON ud.usd_usr_id = u.usr_id
        JOIN {table_prefix}members m ON u.usr_id = m.mem_usr_id
        JOIN {table_prefix}roles r ON m.mem_rol_id = r.rol_id
        WHERE ud.usd_usf_id = %s
          AND ud.usd_value IS NOT NULL
          AND ud.usd_value != ''
          AND u.usr_valid = %s
          AND r.rol_name = %s
          AND (m.mem_end >= CURDATE() OR m.mem_end = %s)
    """

    with conn.cursor() as cursor:
        cursor.execute(
            query,
            (
                SIPPE_FIELD_ID,
                USER_IS_VALID,
                MEMBERS_ROLE_NAME,
                PERMANENT_MEMBERSHIP_END,
            ),
        )
        rows = cursor.fetchall()

    position_to_name = {str(i + 1): name for i, name in enumerate(sippe_names)}

    members = []
    for row in rows:
        position_str = row["usd_value"]
        position = int(position_str)
        sippe_name = position_to_name.get(position_str, f"Unknown({position_str})")

        members.append(
            MemberSippe(
                user_id=row["usd_usr_id"],
                usd_id=row["usd_id"],
                position=position,
                sippe_name=sippe_name,
            )
        )

    return members


def fetch_sippe_state(
    conn: pymysql.Connection,
    table_prefix: str,
) -> SippeState:
    """Fetch complete Sippe state from database."""
    sippe_names = fetch_sippe_names(conn, table_prefix)
    members = fetch_member_assignments(conn, table_prefix, sippe_names)

    member_counts: dict[str, int] = {}
    for member in members:
        member_counts[member.sippe_name] = member_counts.get(member.sippe_name, 0) + 1

    sippe_list = [
        SippeInfo(
            name=name,
            position=i + 1,
            member_count=member_counts.get(name, 0),
        )
        for i, name in enumerate(sippe_names)
    ]

    return SippeState(sippe_list=sippe_list, members=members)


def compute_member_updates(
    members: list[MemberSippe],
    new_sippe_names: list[str],
) -> list[tuple[MemberSippe, int]]:
    """Compute which members need position updates for a new Sippe list."""
    name_to_new_position = {name: i + 1 for i, name in enumerate(new_sippe_names)}

    updates = []
    for member in members:
        new_position = name_to_new_position.get(member.sippe_name)
        if new_position is not None and new_position != member.position:
            updates.append((member, new_position))

    return updates


def plan_add(
    state: SippeState,
    new_sippe_name: str,
) -> MutationPlan:
    """Plan adding a new Sippe."""
    current_names = [s.name for s in state.sippe_list]

    if new_sippe_name in current_names:
        raise SippeAlreadyExistsError(new_sippe_name)

    new_names = sorted([*current_names, new_sippe_name], key=str.lower)
    member_updates = compute_member_updates(state.members, new_names)

    return MutationPlan(
        new_sippe_names=new_names,
        member_updates=member_updates,
        description=f"Add '{new_sippe_name}' and re-sort alphabetically",
    )


def plan_delete(
    state: SippeState,
    sippe_name: str,
    reassign_to: str | None,
) -> MutationPlan:
    """Plan deleting a Sippe."""
    current_names = [s.name for s in state.sippe_list]

    if sippe_name not in current_names:
        raise SippeNotFoundError(sippe_name)

    sippe_info = next(s for s in state.sippe_list if s.name == sippe_name)

    if sippe_info.member_count > 0 and reassign_to is None:
        raise SippeHasMembersError(sippe_name, sippe_info.member_count)

    if reassign_to is not None and reassign_to not in current_names:
        raise SippeNotFoundError(reassign_to)

    if reassign_to == sippe_name:
        raise ValueError("Cannot reassign members to the same Sippe being deleted")

    updated_members = []
    for member in state.members:
        if member.sippe_name == sippe_name and reassign_to is not None:
            updated_members.append(
                MemberSippe(
                    user_id=member.user_id,
                    usd_id=member.usd_id,
                    position=member.position,
                    sippe_name=reassign_to,
                )
            )
        else:
            updated_members.append(member)

    new_names = sorted(
        [name for name in current_names if name != sippe_name],
        key=str.lower,
    )
    member_updates = compute_member_updates(updated_members, new_names)

    description = f"Delete '{sippe_name}'"
    if reassign_to:
        description += (
            f" and reassign {sippe_info.member_count} members to '{reassign_to}'"
        )

    return MutationPlan(
        new_sippe_names=new_names,
        member_updates=member_updates,
        description=description,
    )


def plan_sort(state: SippeState) -> MutationPlan:
    """Plan sorting Sippe list alphabetically."""
    current_names = [s.name for s in state.sippe_list]
    new_names = sorted(current_names, key=str.lower)
    member_updates = compute_member_updates(state.members, new_names)

    return MutationPlan(
        new_sippe_names=new_names,
        member_updates=member_updates,
        description="Sort Sippe list alphabetically",
    )


def is_sorted(state: SippeState) -> bool:
    """Check if Sippe list is already sorted alphabetically."""
    current_names = [s.name for s in state.sippe_list]
    return current_names == sorted(current_names, key=str.lower)


def execute_mutation(
    conn: pymysql.Connection,
    table_prefix: str,
    plan: MutationPlan,
) -> None:
    """Execute a mutation plan within a transaction."""
    new_value_list = "\n".join(plan.new_sippe_names)

    with conn.cursor() as cursor:
        for member, new_position in plan.member_updates:
            cursor.execute(
                f"""
                UPDATE {table_prefix}user_data 
                SET usd_value = %s
                WHERE usd_id = %s
                """,
                (str(new_position), member.usd_id),
            )

        cursor.execute(
            f"""
            UPDATE {table_prefix}user_fields 
            SET usf_value_list = %s
            WHERE usf_id = %s
            """,
            (new_value_list, SIPPE_FIELD_ID),
        )

    conn.commit()
