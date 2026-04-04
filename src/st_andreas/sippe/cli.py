"""CLI for Sippe management.

Commands:
    sippe list                        List Sippe with positions & member counts
    sippe add "Name"                  Add Sippe, sort, reassign members
    sippe delete "Name" --reassign-to Delete Sippe, reassign members, re-sort
    sippe sort                        Sort alphabetically + reassign
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from st_andreas.admidio_db import (
    db_connection,
    load_secrets,
    ssh_tunnel,
)
from st_andreas.sippe.operations import (
    MutationPlan,
    SippeAlreadyExistsError,
    SippeHasMembersError,
    SippeNotFoundError,
    SippeState,
    execute_mutation,
    fetch_sippe_state,
    is_sorted,
    plan_add,
    plan_delete,
    plan_sort,
)

if TYPE_CHECKING:
    import pymysql


def print_sippe_list(state: SippeState) -> None:
    """Print Sippe list with positions and member counts."""
    if not state.sippe_list:
        print("No Sippe entries found.")
        return

    print("Current Sippe list:")
    print()
    total_members = 0
    for sippe in state.sippe_list:
        print(f"  {sippe.position:2d}. {sippe.name} ({sippe.member_count} members)")
        total_members += sippe.member_count

    print()
    print(f"Total: {len(state.sippe_list)} Sippe, {total_members} members assigned")

    if is_sorted(state):
        print("Status: Alphabetically sorted")
    else:
        print("Status: NOT sorted (run 'sippe sort' to fix)")


def print_mutation_plan(plan: MutationPlan, state: SippeState) -> None:
    """Print details of a mutation plan."""
    print(f"Plan: {plan.description}")
    print()

    if plan.member_updates:
        print(f"Members to update: {len(plan.member_updates)}")

        updates_by_sippe: dict[str, list[tuple[int, int]]] = {}
        for member, new_pos in plan.member_updates:
            if member.sippe_name not in updates_by_sippe:
                updates_by_sippe[member.sippe_name] = []
            updates_by_sippe[member.sippe_name].append((member.position, new_pos))

        for sippe_name in sorted(updates_by_sippe.keys(), key=str.lower):
            updates = updates_by_sippe[sippe_name]
            old_pos, new_pos = updates[0]
            print(f"  - {sippe_name}: {len(updates)} members ({old_pos} -> {new_pos})")
    else:
        print("No member position updates needed.")

    print()
    print("New Sippe order:")
    for i, name in enumerate(plan.new_sippe_names, start=1):
        print(f"  {i:2d}. {name}")


def print_backup_reminder() -> None:
    """Print reminder to backup database before mutations."""
    print("IMPORTANT: Make sure you have a recent database backup before proceeding.")
    print()


def confirm_execution() -> bool:
    """Ask user to confirm execution."""
    try:
        response = input("Execute this plan? [y/N] ")
        return response.lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def execute_with_confirmation(
    conn: pymysql.Connection,
    table_prefix: str,
    plan: MutationPlan,
    state: SippeState,
    dry_run: bool,
) -> int:
    """Execute a mutation plan with confirmation."""
    print_mutation_plan(plan, state)

    if dry_run:
        print()
        print("Dry run - no changes made. Remove --dry-run to apply.")
        return 0

    print()
    print_backup_reminder()

    if not confirm_execution():
        print("Aborted.")
        return 1

    print()
    print("Executing...")
    execute_mutation(conn, table_prefix, plan)
    print(f"Done. Updated {len(plan.member_updates)} member records.")
    return 0


def cmd_list(
    conn: pymysql.Connection,
    table_prefix: str,
    _args: argparse.Namespace,
) -> int:
    """Handle 'list' command."""
    state = fetch_sippe_state(conn, table_prefix)
    print_sippe_list(state)
    return 0


def cmd_add(
    conn: pymysql.Connection,
    table_prefix: str,
    args: argparse.Namespace,
) -> int:
    """Handle 'add' command."""
    state = fetch_sippe_state(conn, table_prefix)

    try:
        plan = plan_add(state, args.name)
    except SippeAlreadyExistsError as e:
        print(f"Error: {e}")
        return 1

    return execute_with_confirmation(conn, table_prefix, plan, state, args.dry_run)


def cmd_delete(
    conn: pymysql.Connection,
    table_prefix: str,
    args: argparse.Namespace,
) -> int:
    """Handle 'delete' command."""
    state = fetch_sippe_state(conn, table_prefix)

    try:
        plan = plan_delete(state, args.name, args.reassign_to)
    except (SippeNotFoundError, SippeHasMembersError, ValueError) as e:
        print(f"Error: {e}")
        return 1

    return execute_with_confirmation(conn, table_prefix, plan, state, args.dry_run)


def cmd_sort(
    conn: pymysql.Connection,
    table_prefix: str,
    args: argparse.Namespace,
) -> int:
    """Handle 'sort' command."""
    state = fetch_sippe_state(conn, table_prefix)

    if is_sorted(state):
        print("Sippe list is already sorted alphabetically. Nothing to do.")
        return 0

    plan = plan_sort(state)
    return execute_with_confirmation(conn, table_prefix, plan, state, args.dry_run)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="sippe",
        description="Manage Admidio Sippe field safely with full reassignment",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "list", help="Show current Sippe with positions & member counts"
    )

    add_parser = subparsers.add_parser(
        "add", help="Add new Sippe, sort alphabetically, reassign members"
    )
    add_parser.add_argument("name", help="Name of the new Sippe")
    add_parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Show plan without executing"
    )

    delete_parser = subparsers.add_parser(
        "delete", help="Delete Sippe, reassign members, re-sort"
    )
    delete_parser.add_argument("name", help="Name of the Sippe to delete")
    delete_parser.add_argument(
        "--reassign-to",
        help="Sippe to reassign members to (required if Sippe has members)",
    )
    delete_parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Show plan without executing"
    )

    sort_parser = subparsers.add_parser(
        "sort", help="Sort alphabetically + reassign (if not already sorted)"
    )
    sort_parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Show plan without executing"
    )

    return parser


def run_cli(args: argparse.Namespace) -> int:
    """Run the CLI with parsed arguments."""
    secrets = load_secrets()
    table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]

    command_handlers = {
        "list": cmd_list,
        "add": cmd_add,
        "delete": cmd_delete,
        "sort": cmd_sort,
    }

    handler = command_handlers[args.command]

    with ssh_tunnel(), db_connection() as conn:
        return handler(conn, table_prefix, args)


def main() -> None:
    """Entry point for Sippe CLI."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        sys.exit(run_cli(args))
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
