# St. Andreas Data Pipelines

Data pipelines and tools for St. Andreas Pfadfinder member management.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for package management
- SSH access to Hetzner server (for Admidio database)

## Installation

Install dependencies using uv:

```bash
uv sync
```

## Configuration

Copy the example secrets file and fill in your credentials:

```bash
cp secrets.env.example secrets.env
```

See `secrets.env.example` for all available configuration options.

## Pipelines

### Member Pipelines

The project uses a configurable pipeline system for member data exports. New pipelines can be created by defining a `PipelineConfig` with columns, filters, and export settings.

#### Mitgliederliste (All Members)

Fetches all member data from Admidio database and uploads a styled Excel report to Admidio's document storage.

```bash
uv run fetch-members-all
```

**Features:**
- Fetches MitgliedsNr, Nachname, Vorname, Kontoinhaber, FamilienNr, Sippe
- Maps Sippe IDs to human-readable names
- Sorted by Sippe (ascending), then by Nachname
- Professional Excel styling with headers, alternating rows, filters
- Auto-uploads to Admidio "Dokumente & Dateien" → "Mitgliederliste"
- Timestamped filenames (e.g., `2026-04-01_1605_Mitgliederliste.xlsx`)

#### Members Without Kontoinhaber

Fetches members who don't have a bank account holder (Kontoinhaber) set, including their email addresses.

```bash
uv run fetch-members-no-kontoinhaber
```

**Features:**
- Filters members where Kontoinhaber field is empty
- Includes Email column for follow-up contact
- Same styling and upload behavior as Mitgliederliste

#### Creating New Member Pipelines

To create a new pipeline with different filters or columns:

```python
from st_andreas.admidio_db import AdmidioField
from st_andreas.member_pipeline import (
    ColumnConfig, FilterFieldConfig, PipelineConfig,
    FieldEmptyFilter, FieldEqualsFilter, run_pipeline,
)

CONFIG = PipelineConfig(
    name="my_pipeline",
    description="Pipeline description",
    columns=(
        ColumnConfig("Header", AdmidioField.FIELD_NAME, width=15),
        # ... more columns
    ),
    filter_fields=(
        # Fields needed for filtering but not exported
        FilterFieldConfig("FilterCol", AdmidioField.FILTER_FIELD),
    ),
    filters=(
        FieldEmptyFilter("FilterCol"),
        # FieldNotEmptyFilter, FieldEqualsFilter, FieldContainsFilter
    ),
    filename_prefix="MyExport",
)

def main() -> None:
    run_pipeline(CONFIG)
```

Available filters:
- `FieldEmptyFilter(field_name)` - matches null or empty string
- `FieldNotEmptyFilter(field_name)` - matches non-null, non-empty
- `FieldEqualsFilter(field_name, values)` - matches specific values
- `FieldContainsFilter(field_name, substring)` - matches substring

### SEPA Lastschrift (Direct Debit)

Generates SEPA pain.008.001.02 XML files for annual membership fee collection via direct debit.

```bash
# Generate for current year (collection date: 5 days from today)
uv run sepa-lastschrift

# Specify year and collection date
uv run sepa-lastschrift --year 2026 --collection-date 2026-11-15
```

**Features:**
- Generates bank-importable pain.008.001.02 XML
- Uses Kontoinhaber field with fallback to Vorname + Nachname
- Family deduplication: families (Beitragsstufe 3) share one transaction using FamilienNr
- IBAN normalization and SEPA character sanitization
- Excludes members who already paid or have no IBAN
- Reports excluded members

**Fee structure:**
- Stufe 1/2/5 (Kinder/Jugend, Erwachsene, Unterstützend): 120 EUR
- Stufe 3 (Familie): 180 EUR
- Stufe 4 (Ermäßigt): 24 EUR

**Output:** `src/data/sepa_lastschrift_{year}.xml`

### Spendenquittungen (Donation Receipts)

Fetches member data from Admidio database and generates Excel spreadsheet for mail merge document creation.

```bash
uv run spendenquittungen
```

**Features:**
- Fetches member data directly from Admidio database via SSH tunnel
- Maps membership levels to contribution amounts and German word representations
- Normalizes family member addresses to use the oldest family member's address
- Filters only members with paid contributions
- Generates Excel output for mail merge with Word

**Output:** `data/Spendenquittungen_{year}.xlsx`

### Sippe Management

CLI tool for safely managing the Sippe dropdown field in Admidio. Handles the position-based storage correctly by reassigning all members when the list changes.

```bash
# List current Sippe with member counts
uv run sippe list

# Add a new Sippe (sorts alphabetically, reassigns all members)
uv run sippe add "NewSippe"
uv run sippe add "NewSippe" --dry-run  # Preview changes

# Delete a Sippe (must reassign members first if any)
uv run sippe delete "OldSippe"
uv run sippe delete "OldSippe" --reassign-to "OtherSippe"

# Sort alphabetically (if not already sorted)
uv run sippe sort
```

**Features:**
- Safe position reassignment preserves member-to-Sippe mappings
- `--dry-run` flag to preview changes before execution
- Confirmation prompt with backup reminder
- All changes in a single database transaction

**Why this tool exists:** Admidio stores dropdown values by position number, not name. Adding or deleting items shifts positions and corrupts member assignments. This CLI handles reassignment automatically.

### Database Backup

Automated daily backups of the Admidio MariaDB database.

```bash
# Run backup scheduler (continuous, backs up at 2 AM Europe/Berlin)
uv run backup-scheduler

# Run single backup immediately
uv run backup-scheduler --once
```

**Features:**
- Daily automated backups at 02:00 Europe/Berlin
- Compressed with gzip (~130KB per backup)
- Automatic retention cleanup (default: 30 days)
- Runs as systemd user service

**Backup location:** `backups/admidio_YYYYMMDD_HHMMSS.sql.gz`

#### Systemd Service

The backup scheduler runs as a systemd user service:

```bash
# Check status
systemctl --user status st-andreas-backup

# View logs
journalctl --user -u st-andreas-backup -f

# Restart service
systemctl --user restart st-andreas-backup
```

## Project Structure

```
src/st_andreas/
├── __init__.py
├── admidio_db.py              # Shared database utilities (SSH tunnel, queries)
├── member_pipeline/           # Configurable pipeline infrastructure
│   ├── __init__.py
│   ├── config.py              # PipelineConfig, ColumnConfig dataclasses
│   ├── filters.py             # MemberFilter ABC and filter implementations
│   ├── excel_export.py        # Styled Excel export
│   └── pipeline.py            # run_pipeline() orchestrator
├── pipelines/                 # Pipeline entry points
│   ├── __init__.py
│   ├── fetch_members_all.py   # All members pipeline
│   ├── fetch_members_no_kontoinhaber.py  # Members without Kontoinhaber
│   ├── sepa_lastschrift.py    # SEPA direct debit XML generation
│   └── spendenquittungen.py   # Donation receipts (complex transformations)
├── sepa/                      # SEPA direct debit module
│   ├── __init__.py
│   ├── config.py              # SepaConfig, CreditorConfig, Beitragsstufe
│   ├── transactions.py        # MemberRecord, SepaTransaction, DB fetching
│   └── xml_generator.py       # pain.008.001.02 XML generation
├── sippe/                     # Sippe management CLI
│   ├── __init__.py
│   ├── cli.py                 # CLI entry point (list, add, delete, sort)
│   └── operations.py          # Core database operations
└── backup/
    ├── config.py              # Backup configuration
    ├── dump.py                # Database dump operations
    ├── retention.py           # Backup retention cleanup
    └── scheduler.py           # AioClock scheduler
```

## Testing

Run the test suite:

```bash
uv run pytest
```

**Test Categories:**

- **Unit tests** — Test pure functions with mocked dependencies (always run)
- **Integration tests** — Test database connectivity (skipped without `secrets.env`)

Integration tests are automatically skipped in CI or when `secrets.env` is not present. To run all tests including integration tests locally:

```bash
# Ensure secrets.env exists with valid credentials
uv run pytest -v
```

To run only unit tests:

```bash
uv run pytest -v -m "not requires_database"
```

## Documentation

- `docs/infrastructure.md` - Server access and database credentials
