"""Core pipeline runner for member data exports."""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Final

import pandas as pd

from st_andreas.admidio_db import (
    ADMIDIO_SYSTEM_USER_ID,
    db_connection,
    fetch_field_value_list,
    fetch_user_field_values,
    load_db_config,
    load_secrets,
    load_ssh_config,
    ssh_tunnel,
)
from st_andreas.member_pipeline.config import PipelineConfig
from st_andreas.member_pipeline.excel_export import export_to_excel

ADMIDIO_VOLUME_PATH: Final[str] = (
    "/var/lib/docker/volumes/"
    "756e80f3bc09b1883b34a1389fce457f3561e7711d4ec592edbda3f2b422ad5a/"
    "_data/documents_sta/Mitgliederliste"
)


def _fetch_value_list_mappings(
    config: PipelineConfig,
    table_prefix: str,
) -> dict[str, dict[str, str]]:
    """Fetch value list mappings for all configured value list fields."""
    with db_connection() as conn:
        return {
            field_name: fetch_field_value_list(conn, field_name, table_prefix)
            for field_name in config.value_list_fields
        }


def _fetch_member_data(
    config: PipelineConfig,
    value_list_mappings: dict[str, dict[str, str]],
    table_prefix: str,
) -> pd.DataFrame:
    """Fetch member data from Admidio database based on pipeline config."""
    field_ids = [col.source_field.value for col in config.columns]
    field_ids += [ff.source_field.value for ff in config.filter_fields]

    with db_connection() as conn:
        users = fetch_user_field_values(conn, field_ids, table_prefix)

    all_field_configs = list(config.columns) + list(config.filter_fields)

    rows: list[dict[str, str | None]] = []
    for user_data in users.values():
        row: dict[str, str | None] = {}
        for field_config in all_field_configs:
            field_name = field_config.source_field.name
            value = user_data.get(field_name)

            mapping = value_list_mappings.get(field_name)
            if mapping and value:
                value = mapping.get(value, value)

            row[field_config.header] = value

        rows.append(row)

    return pd.DataFrame(rows)


def _apply_filters(df: pd.DataFrame, config: PipelineConfig) -> pd.DataFrame:
    """Apply all configured filters to the DataFrame."""
    for member_filter in config.filters:
        df = member_filter.apply(df)
    return df


def _drop_filter_only_columns(df: pd.DataFrame, config: PipelineConfig) -> pd.DataFrame:
    """Remove columns that were only needed for filtering."""
    filter_only_headers = [ff.header for ff in config.filter_fields]
    return df.drop(columns=filter_only_headers)


def _sort_data(df: pd.DataFrame, config: PipelineConfig) -> pd.DataFrame:
    """Sort DataFrame by configured columns."""
    existing_sort_cols = [col for col in config.sort_by if col in df.columns]
    if existing_sort_cols:
        return df.sort_values(existing_sort_cols)
    return df


def _generate_filename(config: PipelineConfig) -> str:
    """Generate filename with current date and time."""
    now = datetime.now().strftime("%Y-%m-%d_%H%M")
    return f"{now}_{config.filename_prefix}.xlsx"


def _upload_to_admidio(
    local_file: Path,
    remote_filename: str,
    table_prefix: str,
    folder_id: int,
) -> None:
    """Upload file to Admidio and register in database."""
    ssh_config = load_ssh_config()
    db_config = load_db_config()

    expanded_key_path = Path(ssh_config.key_path).expanduser()
    remote_path = f"{ADMIDIO_VOLUME_PATH}/{remote_filename}"

    scp_cmd = [
        "scp",
        "-i",
        str(expanded_key_path),
        "-o",
        "StrictHostKeyChecking=no",
        str(local_file),
        f"{ssh_config.user}@{ssh_config.host}:{remote_path}",
    ]
    subprocess.run(scp_cmd, check=True)

    chown_cmd = [
        "ssh",
        "-i",
        str(expanded_key_path),
        "-o",
        "StrictHostKeyChecking=no",
        f"{ssh_config.user}@{ssh_config.host}",
        f"chown www-data:www-data '{remote_path}'",
    ]
    subprocess.run(chown_cmd, check=True)

    file_uuid = str(uuid.uuid4())

    with db_connection(db_config) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT fil_id FROM {table_prefix}files 
                WHERE fil_fol_id = %s AND fil_name = %s
                """,
                (folder_id, remote_filename),
            )
            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    f"""
                    UPDATE {table_prefix}files 
                    SET fil_timestamp = NOW()
                    WHERE fil_id = %s
                    """,
                    (existing["fil_id"],),
                )
            else:
                cursor.execute(
                    f"""
                    INSERT INTO {table_prefix}files 
                    (fil_fol_id, fil_uuid, fil_name, fil_locked, fil_counter,
                     fil_usr_id, fil_timestamp)
                    VALUES (%s, %s, %s, 0, 0, %s, NOW())
                    """,
                    (
                        folder_id,
                        file_uuid,
                        remote_filename,
                        ADMIDIO_SYSTEM_USER_ID,
                    ),
                )

        conn.commit()


def run_pipeline(config: PipelineConfig) -> None:
    """Run the complete member data pipeline."""
    secrets = load_secrets()
    table_prefix = secrets["ADMIDIO_TABLE_PREFIX"]

    with ssh_tunnel():
        value_list_mappings = _fetch_value_list_mappings(config, table_prefix)

        df = _fetch_member_data(config, value_list_mappings, table_prefix)
        df = _apply_filters(df, config)
        df = _drop_filter_only_columns(df, config)
        df = _sort_data(df, config)

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = _generate_filename(config)
            local_file = Path(tmpdir) / filename

            export_to_excel(df, config.columns, local_file)

            if config.upload_to_admidio:
                _upload_to_admidio(
                    local_file, filename, table_prefix, config.admidio_folder_id
                )

    print(f"Exported {len(df)} members to {filename}")
