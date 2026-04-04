"""Pipeline to generate SEPA direct debit XML from Admidio data."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

from st_andreas.admidio_db import load_secrets, ssh_tunnel
from st_andreas.sepa import (
    MemberRecord,
    SepaConfig,
    build_sepa_xml,
    build_transactions,
    fetch_sepa_members,
    load_creditor_config,
)

OUTPUT_DIR: Final[Path] = Path(__file__).parent.parent.parent / "data"
DEFAULT_COLLECTION_DAYS_AHEAD: Final[int] = 5


def main() -> None:
    """Generate SEPA direct debit XML from Admidio database."""
    args = _parse_args()

    collection_date = args.collection_date or _default_collection_date()
    year = args.year or collection_date.year

    secrets = load_secrets()
    table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]
    creditor = load_creditor_config(secrets)

    config = SepaConfig(collection_date=collection_date, year=year, creditor=creditor)

    with ssh_tunnel():
        members = fetch_sepa_members(table_prefix, year)

    transactions, excluded = build_transactions(members, config)

    _print_exclusion_report(excluded)

    xml_content = build_sepa_xml(transactions, config)

    output_file = _write_output(xml_content, year)

    _print_summary(transactions, output_file)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SEPA direct debit XML for membership fees"
    )
    parser.add_argument(
        "--collection-date",
        type=_parse_date,
        help="Collection date (YYYY-MM-DD). Default: 5 days from today",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Membership year. Default: collection date year",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file path. Default: data/sepa_lastschrift_<year>.xml",
    )
    return parser.parse_args()


def _parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _default_collection_date() -> date:
    return date.today() + timedelta(days=DEFAULT_COLLECTION_DAYS_AHEAD)


def _write_output(xml_content: bytes, year: int) -> Path:
    output_file = OUTPUT_DIR / f"sepa_lastschrift_{year}.xml"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(xml_content)
    return output_file


def _print_exclusion_report(excluded: list[MemberRecord]) -> None:
    if not excluded:
        return

    print(f"\nExcluded {len(excluded)} members (missing IBAN or Beitragsstufe):")
    for member in excluded:
        reason = "missing IBAN" if not member.iban else "missing Beitragsstufe"
        print(
            f"  - {member.vorname} {member.nachname} ({member.mitglieds_nr}): {reason}"
        )
    print()


def _print_summary(transactions: list, output_file: Path) -> None:
    total = sum(t.amount_eur for t in transactions)
    print(f"Generated {len(transactions)} transactions, total: {total} EUR")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    main()
