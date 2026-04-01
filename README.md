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

```bash
uv run fetch-members
```

**Features:**
- Fetches MitgliedsNr, Nachname, Vorname, Kontoinhaber, FamilienNr, Sippe
- Maps Sippe IDs to human-readable names
- Sorted by Sippe (ascending), then by Nachname
- Professional Excel styling with headers, alternating rows, filters
- Auto-uploads to Admidio "Dokumente & Dateien" → "Mitgliederliste"
- Timestamped filenames (e.g., `2026-04-01_1605_Mitgliederliste.xlsx`)

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

## Project Structure

```
src/st_andreas/
├── __init__.py
├── admidio_db.py       # Shared database utilities (SSH tunnel, queries)
├── fetch_members.py    # Mitgliederliste pipeline
└── spendenquittungen.py # Spendenquittungen pipeline
```

## Documentation

- `docs/infrastructure.md` - Server access and database credentials
