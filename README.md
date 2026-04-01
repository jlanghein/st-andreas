# Spendenquittungen

Convert member data from CSV to Excel spreadsheet for mail merge document creation in Microsoft Word.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for package management

## Installation

Install dependencies using uv:

```bash
uv sync
```

## Usage

Run the transformation:

```bash
uv run python Spendenquittungen.py
```

This will read member data from `data/mitglieder.csv` and generate an Excel file at `data/Spendenquittungen_{YEAR}.xlsx`.

## Features

- Loads member data exported from Admidio
- Maps membership levels to contribution amounts and German word representations
- Normalizes family member addresses to use the oldest family member's address
- Filters only members with paid contributions
- Generates Excel output for mail merge with Word

## Configuration

Edit the following in `Spendenquittungen.py` to customize:

- `METADATA`: Period, exemption date, and year range
- `BEITRAGS_CONFIG`: Membership level mappings and amounts
- `OUTPUT_COLS`: Columns included in the output spreadsheet
