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

Create a `secrets.env` file with the required credentials (see `docs/infrastructure.md` for details):

```bash
# Admidio Database
ADMIDIO_DB_NAME=admidio
ADMIDIO_DB_USER=admidio
ADMIDIO_DB_PASSWORD=<password>
ADMIDIO_TABLE_PREFIX=adm_

# Hetzner SSH Access
HETZNER_SSH_HOST=<ip>
HETZNER_SSH_USER=root
HETZNER_SSH_KEY_PATH=~/.ssh/hetzner_key
```

## Pipelines

### Mitgliederliste (Member List)

Fetches member data from Admidio database and uploads a styled Excel report to Admidio's document storage.

**Run:**
```bash
uv run python -c "from fetch_members import main; main()"
```

**Features:**
- Fetches MitgliedsNr, Nachname, Vorname, Kontoinhaber, FamilienNr, Sippe
- Maps Sippe IDs to human-readable names
- Sorted by Sippe (ascending), then by Nachname
- Professional Excel styling with headers, alternating rows, filters
- Auto-uploads to Admidio "Dokumente & Dateien" → "Mitgliederliste"
- Timestamped filenames (e.g., `2026-04-01_1605_Mitgliederliste.xlsx`)

### Spendenquittungen (Donation Receipts)

Converts member data to Excel spreadsheet for mail merge document creation.

**Run:**
```bash
uv run python Spendenquittungen.py
```

**Features:**
- Loads member data exported from Admidio
- Maps membership levels to contribution amounts and German word representations
- Normalizes family member addresses to use the oldest family member's address
- Filters only members with paid contributions
- Generates Excel output for mail merge with Word

**Configuration:** Edit `Spendenquittungen.py` to customize:
- `METADATA`: Period, exemption date, and year range
- `BEITRAGS_CONFIG`: Membership level mappings and amounts
- `OUTPUT_COLS`: Columns included in the output spreadsheet

## Documentation

- `docs/infrastructure.md` - Server access and database credentials
