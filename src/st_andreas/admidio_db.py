"""Shared utilities for Admidio database access."""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pymysql
import pymysql.cursors

if TYPE_CHECKING:
    from collections.abc import Iterator

SECRETS_FILE: Final[Path] = Path(__file__).parent.parent.parent / "secrets.env"

SSH_TUNNEL_LOCAL_PORT: Final[int] = 13306
SSH_TUNNEL_REMOTE_PORT: Final[int] = 3306
# Default tunnel target: the MariaDB container's address on the Docker bridge.
# This is a fragile default -- Docker renumbers bridges -- and it is only still
# here because the original Hetzner host (ubuntu-sta, 91.98.90.85) published no
# port for the database. Override it with ADMIDIO_TUNNEL_TARGET in secrets.env;
# the Oerenburg host publishes 127.0.0.1:3306 and uses that instead.
DOCKER_DB_HOST: Final[str] = "172.18.0.2"

MEMBERS_ROLE_NAME: Final[str] = "StA-Mitglieder"
PERMANENT_MEMBERSHIP_END: Final[str] = "9999-12-31"


class AdmidioField(Enum):
    """Admidio user field IDs mapped to their internal names.

    These IDs correspond to usf_id in the adm_user_fields table.
    """

    LAST_NAME = 1
    FIRST_NAME = 2
    STREET = 3
    POSTCODE = 4
    CITY = 5
    PHONE = 7
    MOBILE = 8
    BIRTHDAY = 9
    EMAIL = 11

    MITGLIEDSNR = 20
    FAMILIENNR = 21
    CO = 22
    EMAIL2 = 23
    SIPPE = 24
    BEITRAGSSTUFE = 25
    BEITRITTSDATUM = 26
    BEITRAG_2025_BEZAHLT = 27
    ANREDE = 28
    VERMERK = 29
    IBAN = 30
    BIC = 31
    KONTOINHABER = 32
    FOERDERBEITRAG = 33
    BEITRAG_2026_BEZAHLT = 34


@dataclass
class AdmidioConfig:
    """Database connection configuration."""

    host: str
    port: int
    database: str
    user: str
    password: str
    table_prefix: str


@dataclass
class SSHConfig:
    """SSH tunnel configuration."""

    host: str
    user: str
    key_path: str
    tunnel_target: str = DOCKER_DB_HOST
    proxy_jump: str | None = None


def load_secrets(path: Path | None = None) -> dict[str, str]:
    """Load environment variables from a secrets file."""
    if path is None:
        path = SECRETS_FILE

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


def load_ssh_config(secrets: dict[str, str] | None = None) -> SSHConfig:
    """Load SSH configuration from secrets."""
    if secrets is None:
        secrets = load_secrets()

    # The HETZNER_* names are historical: the database moved from the Hetzner
    # vServer to Oerenburg VM 317, which is reachable only through a jump host.
    return SSHConfig(
        host=secrets["HETZNER_SSH_HOST"],
        user=secrets["HETZNER_SSH_USER"],
        key_path=secrets["HETZNER_SSH_KEY_PATH"],
        tunnel_target=secrets.get("ADMIDIO_TUNNEL_TARGET", DOCKER_DB_HOST),
        proxy_jump=secrets.get("HETZNER_SSH_PROXYJUMP") or None,
    )


def load_db_config(secrets: dict[str, str] | None = None) -> AdmidioConfig:
    """Load database configuration from secrets."""
    if secrets is None:
        secrets = load_secrets()

    return AdmidioConfig(
        host="127.0.0.1",
        port=SSH_TUNNEL_LOCAL_PORT,
        database=secrets["ADMIDIO_DB_NAME"],
        user=secrets["ADMIDIO_DB_USER"],
        password=secrets["ADMIDIO_DB_PASSWORD"],
        table_prefix=secrets["ADMIDIO_TABLE_PREFIX"],
    )


@contextmanager
def ssh_tunnel(config: SSHConfig | None = None) -> Iterator[None]:
    """Create an SSH tunnel to access remote database."""
    if config is None:
        config = load_ssh_config()

    expanded_key_path = Path(config.key_path).expanduser()
    cmd = [
        "ssh",
        "-i",
        str(expanded_key_path),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ExitOnForwardFailure=yes",
        "-L",
        f"{SSH_TUNNEL_LOCAL_PORT}:{config.tunnel_target}:{SSH_TUNNEL_REMOTE_PORT}",
        "-N",
    ]
    if config.proxy_jump:
        cmd += ["-J", config.proxy_jump]
    cmd.append(f"{config.user}@{config.host}")
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


@contextmanager
def db_connection(config: AdmidioConfig | None = None) -> Iterator[pymysql.Connection]:
    """Create a database connection with DictCursor."""
    if config is None:
        config = load_db_config()

    with pymysql.connect(
        host=config.host,
        port=config.port,
        database=config.database,
        user=config.user,
        password=config.password,
        cursorclass=pymysql.cursors.DictCursor,
    ) as conn:
        yield conn


def fetch_user_field_values(
    conn: pymysql.Connection,
    field_ids: list[int],
    table_prefix: str,
) -> dict[int, dict[str, str | None]]:
    """Fetch user data for specified field IDs.

    Only returns users with active membership in the members role.
    A membership is active if mem_end >= today or mem_end is the permanent date.

    Returns a dict mapping user_id to a dict of field_name -> value.
    """
    field_id_placeholders = ",".join("%s" for _ in field_ids)

    query = f"""
        SELECT
            u.usr_id,
            uf.usf_name_intern,
            ud.usd_value
        FROM {table_prefix}users u
        JOIN {table_prefix}user_data ud ON u.usr_id = ud.usd_usr_id
        JOIN {table_prefix}user_fields uf ON ud.usd_usf_id = uf.usf_id
        JOIN {table_prefix}members m ON u.usr_id = m.mem_usr_id
        JOIN {table_prefix}roles r ON m.mem_rol_id = r.rol_id
        WHERE uf.usf_id IN ({field_id_placeholders})
          AND u.usr_valid = 1
          AND r.rol_name = %s
          AND (m.mem_end >= CURDATE() OR m.mem_end = %s)
        ORDER BY u.usr_id
    """

    query_params = (*field_ids, MEMBERS_ROLE_NAME, PERMANENT_MEMBERSHIP_END)

    with conn.cursor() as cursor:
        cursor.execute(query, query_params)
        rows = cursor.fetchall()

    users: dict[int, dict[str, str | None]] = {}
    for row in rows:
        usr_id = row["usr_id"]
        field_name = row["usf_name_intern"]
        value = row["usd_value"]

        if usr_id not in users:
            users[usr_id] = {}

        users[usr_id][field_name] = value

    return users


def fetch_field_value_list(
    conn: pymysql.Connection,
    field_name: str,
    table_prefix: str,
) -> dict[str, str]:
    """Fetch value list mapping for a dropdown/select field.

    Returns a dict mapping numeric ID (as string) to display value.
    """
    query = f"""
        SELECT usf_value_list 
        FROM {table_prefix}user_fields 
        WHERE usf_name_intern = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(query, (field_name,))
        result = cursor.fetchone()

    if not result or not result["usf_value_list"]:
        return {}

    values = result["usf_value_list"].split("\n")
    return {str(i + 1): name.strip() for i, name in enumerate(values)}
