"""Pipeline to fetch member data from Admidio and export to Excel."""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

import pymysql
import pymysql.cursors
from openpyxl import Workbook

SECRETS_FILE: Final = Path(__file__).parent / "secrets.env"
OUTPUT_DIR: Final = Path(__file__).parent / "data"
OUTPUT_FILE: Final = OUTPUT_DIR / "mitglieder.xlsx"

SSH_TUNNEL_LOCAL_PORT: Final = 13306
SSH_TUNNEL_REMOTE_PORT: Final = 3306
DOCKER_DB_HOST: Final = "172.18.0.2"


class AdmidioField(Enum):
    """Admidio user field IDs mapped to their internal names."""

    MITGLIEDSNR = 20
    FAMILIENNR = 21
    SIPPE = 24
    KONTOINHABER = 32
    LAST_NAME = 1
    FIRST_NAME = 2


@dataclass
class MemberRecord:
    """Member data record."""

    mitglieds_nr: str | None = None
    nachname: str | None = None
    vorname: str | None = None
    kontoinhaber: str | None = None
    familien_nr: str | None = None
    sippe: str | None = None


COLUMN_HEADERS: Final = [
    "MitgliedsNr",
    "Nachname",
    "Vorname",
    "Kontoinhaber",
    "FamilienNr",
    "Sippe",
]

FIELD_TO_ATTR: Final[dict[str, str]] = {
    "MITGLIEDSNR": "mitglieds_nr",
    "LAST_NAME": "nachname",
    "FIRST_NAME": "vorname",
    "KONTOINHABER": "kontoinhaber",
    "FAMILIENNR": "familien_nr",
    "SIPPE": "sippe",
}


def load_secrets(path: Path) -> dict[str, str]:
    """Load environment variables from a secrets file."""
    secrets: dict[str, str] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                secrets[key.strip()] = value.strip()
    return secrets


@contextmanager
def ssh_tunnel(
    ssh_host: str,
    ssh_user: str,
    ssh_key_path: str,
    local_port: int,
    remote_host: str,
    remote_port: int,
):
    """Create an SSH tunnel to access remote database."""
    expanded_key_path = Path(ssh_key_path).expanduser()
    cmd = [
        "ssh",
        "-i",
        str(expanded_key_path),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ExitOnForwardFailure=yes",
        "-L",
        f"{local_port}:{remote_host}:{remote_port}",
        "-N",
        f"{ssh_user}@{ssh_host}",
    ]
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    if process.poll() is not None:
        raise RuntimeError("SSH tunnel failed to start")

    try:
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def fetch_member_data(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    table_prefix: str,
) -> list[MemberRecord]:
    """Fetch member data from Admidio database."""
    field_ids = [f.value for f in AdmidioField]

    query = f"""
        SELECT
            u.usr_id,
            uf.usf_name_intern,
            ud.usd_value
        FROM {table_prefix}users u
        JOIN {table_prefix}user_data ud ON u.usr_id = ud.usd_usr_id
        JOIN {table_prefix}user_fields uf ON ud.usd_usf_id = uf.usf_id
        WHERE uf.usf_id IN ({",".join(str(fid) for fid in field_ids)})
          AND u.usr_valid = 1
        ORDER BY u.usr_id
    """

    with pymysql.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        cursorclass=pymysql.cursors.DictCursor,
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

    members_by_id: dict[int, MemberRecord] = {}
    for row in rows:
        usr_id = row["usr_id"]
        field_name = row["usf_name_intern"]
        value = row["usd_value"]

        if usr_id not in members_by_id:
            members_by_id[usr_id] = MemberRecord()

        attr_name = FIELD_TO_ATTR.get(field_name)
        if attr_name:
            setattr(members_by_id[usr_id], attr_name, value)

    return list(members_by_id.values())


def export_to_excel(members: list[MemberRecord], output_path: Path) -> None:
    """Export member records to Excel file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Mitglieder"

    ws.append(COLUMN_HEADERS)

    for member in members:
        ws.append(
            [
                member.mitglieds_nr,
                member.nachname,
                member.vorname,
                member.kontoinhaber,
                member.familien_nr,
                member.sippe,
            ]
        )

    wb.save(output_path)


def main() -> None:
    """Main entry point for the member data pipeline."""
    secrets = load_secrets(SECRETS_FILE)

    ssh_host = secrets["HETZNER_SSH_HOST"]
    ssh_user = secrets["HETZNER_SSH_USER"]
    ssh_key_path = secrets["HETZNER_SSH_KEY_PATH"]

    db_name = secrets["ADMIDIO_DB_NAME"]
    db_user = secrets["ADMIDIO_DB_USER"]
    db_password = secrets["ADMIDIO_DB_PASSWORD"]
    table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]

    with ssh_tunnel(
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key_path,
        local_port=SSH_TUNNEL_LOCAL_PORT,
        remote_host=DOCKER_DB_HOST,
        remote_port=SSH_TUNNEL_REMOTE_PORT,
    ):
        members = fetch_member_data(
            host="127.0.0.1",
            port=SSH_TUNNEL_LOCAL_PORT,
            database=db_name,
            user=db_user,
            password=db_password,
            table_prefix=table_prefix,
        )

    export_to_excel(members, OUTPUT_FILE)
    print(f"Exported {len(members)} members to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
