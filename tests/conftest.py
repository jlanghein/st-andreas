"""Shared test fixtures."""

from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from st_andreas.spendenquittungen import Beitragsstufe, MemberRecord


@pytest.fixture
def secrets_file() -> Path:
    """Create a temporary secrets file for testing."""
    content = """# Test secrets file
ADMIDIO_DB_NAME=test_db
ADMIDIO_DB_USER=test_user
ADMIDIO_DB_PASSWORD=test_password
ADMIDIO_TABLE_PREFIX=adm_

HETZNER_SSH_HOST=192.168.1.1
HETZNER_SSH_USER=testuser
HETZNER_SSH_KEY_PATH=~/.ssh/test_key
"""
    with NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write(content)
        return Path(f.name)


@pytest.fixture
def sample_members() -> list[MemberRecord]:
    """Sample member records for testing transformations."""
    return [
        MemberRecord(
            mitglieds_nr="JD010190",
            familien_nr=None,
            vorname="John",
            nachname="Doe",
            anrede="Herr",
            strasse="Main Street 1",
            plz="12345",
            ort="Berlin",
            geburtstag=date(1990, 1, 1),
            beitragsstufe=Beitragsstufe.ERWACHSENE,
            beitrag_bezahlt=True,
        ),
        MemberRecord(
            mitglieds_nr="JD020185",
            familien_nr="FAM001",
            vorname="Jane",
            nachname="Doe",
            anrede="Frau",
            strasse="Family Lane 5",
            plz="54321",
            ort="Munich",
            geburtstag=date(1985, 2, 15),
            beitragsstufe=Beitragsstufe.FAMILIE,
            beitrag_bezahlt=True,
        ),
        MemberRecord(
            mitglieds_nr="JD030110",
            familien_nr="FAM001",
            vorname="Jimmy",
            nachname="Doe",
            anrede="Herr",
            strasse="Other Street 10",
            plz="11111",
            ort="Hamburg",
            geburtstag=date(2010, 3, 20),
            beitragsstufe=Beitragsstufe.FAMILIE,
            beitrag_bezahlt=True,
        ),
        MemberRecord(
            mitglieds_nr="AS040195",
            familien_nr=None,
            vorname="Alice",
            nachname="Smith",
            anrede="Frau",
            strasse="Oak Avenue 7",
            plz="99999",
            ort="Frankfurt",
            geburtstag=date(1995, 4, 10),
            beitragsstufe=Beitragsstufe.ERMAESSIGT,
            beitrag_bezahlt=False,
        ),
    ]


@pytest.fixture
def beitragsstufe_mapping() -> dict[str, str]:
    """Beitragsstufe field value mapping from database."""
    return {
        "1": "Stufe I: Kinder- und Jugendbeitrag (120,-)",
        "2": "Stufe II: Erwachsenenbeitrag (120,-)",
        "3": "Stufe III: Familienbeitrag (180,-)",
        "4": "Stufe IV: Ermäßigter Beitrag (24,-)",
        "5": "Stufe V: Unterstützende Mitglieder (120,-)",
    }
