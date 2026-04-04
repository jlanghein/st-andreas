"""SIPPE alphabetical cleanup for Admidio.

This module provides a one-time cleanup to alphabetically sort the SIPPE list
while correctly reassigning all member positions.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pymysql.cursors

from st_andreas.admidio_db import (
    MEMBERS_ROLE_NAME,
    PERMANENT_MEMBERSHIP_END,
    AdmidioField,
    db_connection,
    load_secrets,
    ssh_tunnel,
)

if TYPE_CHECKING:
    import pymysql


SIPPE_FIELD_ID: Final[int] = AdmidioField.SIPPE.value


@dataclass(frozen=True)
class SippeInfo:
    """Information about a single SIPPE."""

    name: str
    current_position: int
    member_count: int


@dataclass(frozen=True)
class MemberSippe:
    """A member's SIPPE assignment."""

    user_id: int
    usd_id: int
    current_position: int
    sippe_name: str


@dataclass(frozen=True)
class CleanupPlan:
    """Plan for SIPPE cleanup operation."""

    current_sippe_list: list[SippeInfo]
    sorted_sippe_list: list[SippeInfo]
    members_to_update: list[tuple[MemberSippe, int]]  # (member, new_position)
    is_already_sorted: bool


def fetch_sippe_value_list(
    conn: pymysql.Connection,
    table_prefix: str,
) -> list[str]:
    """Fetch the raw SIPPE value list from the database."""
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


def fetch_member_sippe_assignments(
    conn: pymysql.Connection,
    table_prefix: str,
    sippe_names: list[str],
) -> list[MemberSippe]:
    """Fetch all members with their SIPPE assignments."""
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
          AND u.usr_valid = 1
          AND r.rol_name = %s
          AND (m.mem_end >= CURDATE() OR m.mem_end = %s)
    """

    with conn.cursor() as cursor:
        cursor.execute(
            query, (SIPPE_FIELD_ID, MEMBERS_ROLE_NAME, PERMANENT_MEMBERSHIP_END)
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
                current_position=position,
                sippe_name=sippe_name,
            )
        )

    return members


def build_cleanup_plan(
    sippe_names: list[str],
    members: list[MemberSippe],
) -> CleanupPlan:
    """Build a plan for the cleanup operation."""
    member_counts: dict[str, int] = {}
    for member in members:
        member_counts[member.sippe_name] = member_counts.get(member.sippe_name, 0) + 1

    current_sippe_list = [
        SippeInfo(
            name=name,
            current_position=i + 1,
            member_count=member_counts.get(name, 0),
        )
        for i, name in enumerate(sippe_names)
    ]

    sorted_names = sorted(sippe_names, key=str.lower)
    name_to_new_position = {name: i + 1 for i, name in enumerate(sorted_names)}

    sorted_sippe_list = [
        SippeInfo(
            name=name,
            current_position=name_to_new_position[name],
            member_count=member_counts.get(name, 0),
        )
        for name in sorted_names
    ]

    members_to_update = []
    for member in members:
        new_position = name_to_new_position[member.sippe_name]
        if new_position != member.current_position:
            members_to_update.append((member, new_position))

    is_already_sorted = sippe_names == sorted_names

    return CleanupPlan(
        current_sippe_list=current_sippe_list,
        sorted_sippe_list=sorted_sippe_list,
        members_to_update=members_to_update,
        is_already_sorted=is_already_sorted,
    )


def print_plan(plan: CleanupPlan) -> None:
    """Print the cleanup plan to stdout."""
    print("Current SIPPE order:")
    for sippe in plan.current_sippe_list:
        pos = sippe.current_position
        count = sippe.member_count
        print(f"  {pos:2d}: {sippe.name} ({count} members)")

    print()

    if plan.is_already_sorted:
        print("SIPPE list is already sorted alphabetically. No changes needed.")
        return

    print("After alphabetical sort:")
    old_positions = {s.name: s.current_position for s in plan.current_sippe_list}
    for sippe in plan.sorted_sippe_list:
        old_pos = old_positions[sippe.name]
        if old_pos == sippe.current_position:
            status = "unchanged"
        else:
            status = f"was position {old_pos}"
        pos = sippe.current_position
        count = sippe.member_count
        print(f"  {pos:2d}: {sippe.name} ({count} members) - {status}")

    print()
    print(f"Members to update: {len(plan.members_to_update)}")

    updates_by_sippe: dict[str, list[tuple[int, int]]] = {}
    for member, new_pos in plan.members_to_update:
        if member.sippe_name not in updates_by_sippe:
            updates_by_sippe[member.sippe_name] = []
        updates_by_sippe[member.sippe_name].append((member.current_position, new_pos))

    for sippe_name in sorted(updates_by_sippe.keys(), key=str.lower):
        updates = updates_by_sippe[sippe_name]
        old_pos, new_pos = updates[0]
        print(f"  - {sippe_name}: {len(updates)} members ({old_pos} -> {new_pos})")


def execute_cleanup(
    conn: pymysql.Connection,
    table_prefix: str,
    plan: CleanupPlan,
) -> None:
    """Execute the cleanup operation within a transaction."""
    if plan.is_already_sorted:
        print("Nothing to do - already sorted.")
        return

    sorted_names = [s.name for s in plan.sorted_sippe_list]
    new_value_list = "\n".join(sorted_names)

    with conn.cursor() as cursor:
        for member, new_position in plan.members_to_update:
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

    print()
    print(f"Updated {len(plan.members_to_update)} member records.")
    print("Updated SIPPE value list to alphabetical order.")
    print("Cleanup completed successfully.")


def verify_cleanup(
    conn: pymysql.Connection,
    table_prefix: str,
    expected_member_count: int,
) -> bool:
    """Verify the cleanup was successful."""
    sippe_names = fetch_sippe_value_list(conn, table_prefix)
    members = fetch_member_sippe_assignments(conn, table_prefix, sippe_names)

    sorted_names = sorted(sippe_names, key=str.lower)
    if sippe_names != sorted_names:
        print("ERROR: SIPPE list is not sorted!")
        return False

    if len(members) != expected_member_count:
        expected = expected_member_count
        actual = len(members)
        print(f"ERROR: Member count mismatch! Expected {expected}, got {actual}")
        return False

    name_to_position = {name: i + 1 for i, name in enumerate(sippe_names)}
    for member in members:
        expected_position = name_to_position.get(member.sippe_name)
        if expected_position != member.current_position:
            print(
                f"ERROR: Member {member.user_id} has wrong position! "
                f"Expected {expected_position}, got {member.current_position}"
            )
            return False

    print()
    print("Verification passed:")
    print(f"  - SIPPE list is alphabetically sorted ({len(sippe_names)} entries)")
    print(f"  - All {len(members)} member assignments are correct")
    return True


def run_cleanup(dry_run: bool = True) -> int:
    """Run the SIPPE cleanup operation.

    Returns 0 on success, 1 on error.
    """
    secrets = load_secrets()
    table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]

    with ssh_tunnel(), db_connection() as conn:
        sippe_names = fetch_sippe_value_list(conn, table_prefix)
        if not sippe_names:
            print("ERROR: No SIPPE values found in database.")
            return 1

        members = fetch_member_sippe_assignments(conn, table_prefix, sippe_names)
        plan = build_cleanup_plan(sippe_names, members)

        print_plan(plan)

        if plan.is_already_sorted:
            return 0

        if dry_run:
            print()
            print("Run without --dry-run to apply changes.")
            return 0

        print()
        print("Executing cleanup...")
        execute_cleanup(conn, table_prefix, plan)

        if not verify_cleanup(conn, table_prefix, len(members)):
            return 1

    return 0


def main() -> None:
    """Entry point for SIPPE cleanup CLI."""
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    if not dry_run:
        print("WARNING: This will modify the database!")
        print("Make sure you have a recent backup.")
        print()

    sys.exit(run_cleanup(dry_run=dry_run))


if __name__ == "__main__":
    main()
