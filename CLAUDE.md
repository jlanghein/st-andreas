# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Conventions

`AGENTS.md` holds the development conventions (functional style, error handling, no error suppression, commit format, inline-snapshot testing). Read it before making changes. Two caveats where it contradicts this repo:

- Its "Project Structure" section describes a different project (AudITScraper) — ignore it, use the layout below.
- Its "Mandatory Libraries" table prescribes polars/httpx. This repo uses **pandas** throughout (`member_pipeline`, `spendenquittungen`); match the existing code rather than introducing polars.

## Commands

```bash
uv sync                                   # install deps
uv run pytest                             # full suite (-v is default via pyproject)
uv run pytest tests/test_sepa.py::TestBuildTransactions::test_name   # single test
CI=true uv run pytest                     # unit tests only (skips DB integration tests)
uv run pytest --inline-snapshot=fix       # update snapshots after intentional data changes

uvx ruff format . && uvx ruff check --fix . && uvx ty check .
```

Note: `pytest -m "not requires_database"` (as README suggests) does **not** work — `requires_database` in `tests/test_integration.py` is a `skipif` variable, not a registered marker. Integration tests skip automatically when `CI=true` or `secrets.env` is absent.

Entry points are console scripts declared in `pyproject.toml` (`uv run fetch-members-all`, `sepa-lastschrift`, `spendenquittungen`, `sippe`, `members-27-plus`, `backup-scheduler`). See README for per-pipeline flags. `sepa_plausibility_check` has no console script yet — run it as `uv run python -m st_andreas.pipelines.sepa_plausibility_check`.

## Architecture

Everything reads from a single source of truth: the **Admidio MariaDB** running in Docker on the server, reachable only through an SSH tunnel. **Which server is moving** -- see *Deployment* below; nothing in the code names a host, it all comes from `secrets.env`.

**`admidio_db.py` is the foundation layer** — every other module depends on it and it imports nothing internal. It owns:

- `load_secrets()` — parses `secrets.env` at the repo root (not python-dotenv; a hand-rolled `KEY=VALUE` reader). Missing keys raise `KeyError` at call time.
- `ssh_tunnel()` / `db_connection()` — context managers. The tunnel forwards `localhost:13306` → whatever `ADMIDIO_TUNNEL_TARGET` names, defaulting to the Admidio container's bridge IP `172.18.0.2:3306` (the Hetzner box publishes no port for MariaDB, so there was nothing better to aim at). It also passes `-J` when `HETZNER_SSH_PROXYJUMP` is set. **All DB work must happen inside `with ssh_tunnel():`**; `db_connection()` alone will fail.
- `AdmidioField` enum — the mapping from Admidio `usf_id` integers to internal field names. This is the domain vocabulary; never hardcode a field id elsewhere. Admidio's EAV schema (`adm_user_data` rows keyed by `usd_usf_id`) means adding a field to a query means adding an id to this enum.
- `fetch_user_field_values()` — pivots the EAV rows into `{usr_id: {FIELD_NAME: value}}`, already scoped to *active* members (role `StA-Mitglieder`, `mem_end >= CURDATE()` or the sentinel `9999-12-31`). Pipelines therefore never filter for membership themselves.

**Two Admidio storage quirks drive most of the non-obvious code:**

1. **Dropdown fields store a 1-based position, not a name.** `usf_value_list` is a newline-separated list; a member's stored value is the index into it. `fetch_field_value_list()` resolves position → name (this is what `PipelineConfig.value_list_fields` triggers). Consequently, editing the Sippe list reorders positions and silently corrupts every member's assignment — which is the entire reason `sippe/` exists: it computes a `MutationPlan` reassigning all members and applies it in one transaction.
2. **Payment status is a per-year field** (`BEITRAG_2025_BEZAHLT` = 27, `BEITRAG_2026_BEZAHLT` = 34). A new billing year needs a new enum member *and* an entry in `_get_beitrag_field_for_year()` in `sepa/transactions.py`, which raises `ValueError` for unknown years.

**Member pipelines are declarative.** A file in `pipelines/` defines a `PipelineConfig` and calls `run_pipeline(CONFIG)`; the whole fetch → filter → drop-filter-columns → sort → style → upload sequence lives in `member_pipeline/pipeline.py`. Add a report by writing a config, not by writing a pipeline. Fields used only for filtering go in `filter_fields` (fetched, then dropped before export). `run_pipeline` also **uploads to the live Admidio instance** by default (`upload_to_admidio=True`): scp to `/tmp`, `sudo install -o www-data` into the Docker volume named by `ADMIDIO_DOCUMENTS_PATH`, then an INSERT/UPDATE into `adm_files` so the file appears in "Dokumente & Dateien". Set `upload_to_admidio=False` when experimenting. The two-step staging exists because the destination is inside a root-owned Docker volume: scp'ing straight there only works when the SSH user *is* root, which is true on the Hetzner box and not on its replacement.

**SEPA** (`sepa/`) is layered config → transactions → xml_generator, with `pipelines/sepa_lastschrift.py` as the entry point. `build_transactions()` returns `(transactions, excluded)`; exclusion (already paid, no IBAN, no Beitragsstufe) is a normal outcome that gets reported, not an error. Families (Beitragsstufe 3) collapse to one transaction via a mandate id derived from `FamilienNr`. `xml_generator.py` emits pain.008.001.02 with lxml and sanitizes names against the SEPA charset. Output goes to `src/data/` (gitignored).

**`spendenquittungen.py` is deliberately not a member pipeline** — its transformations (family address normalization to the oldest member, amount-to-German-word mapping) don't fit the config model. It defines its *own* `Beitragsstufe` and `MemberRecord`, distinct from `sepa/config.py`'s versions with the same names. Check which one you're importing.

**`backup/`** is an AioClock scheduler (`backup-scheduler`) running as a systemd *user* service; it shells out to `mysqldump` over SSH and prunes by age. Its config comes from the same `secrets.env`.

## Local state

`secrets.env`, `data/`, `src/data/`, `backups/`, and `StAndreas/` (legacy Jupyter notebooks, superseded by `src/`) are all gitignored. `docs/infrastructure.md` documents the server, DB, and systemd setup.

## Deployment

> **The database host is moving.** The Hetzner vServer `ubuntu-sta` is still
> authoritative; Oerenburg **VM 317** is built, seeded and verified but not yet
> live. Cutover is the `sta.hg-hausverwalter.de` DNS change. Host-level
> documentation for both machines lives in the ServerDeployment repo at
> `docs/langhein/st-andreas-hetzner.md`; this section covers only what this
> repo needs to know.

|  | Hetzner `ubuntu-sta` (today) | Oerenburg VM 317 (after cutover) |
|---|---|---|
| SSH | `root@91.98.90.85`, `~/.ssh/hetzner_key` | `jlanghein@10.25.10.7`, `~/.ssh/id_ed25519` |
| Route | direct | **only** via `-J jol@10.10.10.55` -- nothing else reaches `10.25.10.x` |
| DB tunnel target | `172.18.0.2:3306` (container bridge IP) | `127.0.0.1:3306` (published on loopback) |
| Documents volume | anonymous volume `756e80f3...` | named volume `st-andreas_admidio_files` |
| Upload user | `root` (writes the volume directly) | `jlanghein` + `sudo` |
| phpMyAdmin | `http://91.98.90.85:8081`, now loopback-only | not deployed -- use `ssh -L` |
| Admidio | `admidio/admidio:latest`, pulled once in 2025 | pinned **by digest** (`sha256:bd24f79a…`) |

### The four keys that switch hosts

All live in `secrets.env` (gitignored). A comment block above `HETZNER_SSH_HOST`
holds the replacement lines ready to uncomment.

| Key | Old host | New host |
|---|---|---|
| `HETZNER_SSH_HOST` / `_USER` / `_KEY_PATH` | `91.98.90.85`, `root`, `hetzner_key` | `10.25.10.7`, `jlanghein`, `id_ed25519` |
| `HETZNER_SSH_PROXYJUMP` | unset | `jol@10.10.10.55` |
| `ADMIDIO_TUNNEL_TARGET` | unset (defaults to `172.18.0.2`) | `127.0.0.1` |
| `ADMIDIO_DOCUMENTS_PATH` | unset (defaults to the anonymous volume hash) | `/var/lib/docker/volumes/st-andreas_admidio_files/_data/documents_sta/Mitgliederliste` |

The last two are **required** on the new host, not optional. Their built-in
defaults are properties of the Hetzner box that do not exist anywhere else: a
Docker-assigned bridge address, and an anonymous volume id. Miss
`ADMIDIO_DOCUMENTS_PATH` and every pipeline's upload step scp's into a
directory that is not there.

The `HETZNER_*` names are kept deliberately -- renaming them would touch every
caller for no behavioural gain. Read them as "the database host".

### Why the documents path is not the obvious one

On the Hetzner box the compose file mounts a *named* volume
(`admidio_admidio_files`) at `/var/www/html/adm_my_files` -- **a path this
Admidio image does not use.** Its document root is `/opt/app-root/src`, so the
real files were written into an anonymous volume created by the image's own
`VOLUME` directive, which is where the hash in `ADMIDIO_VOLUME_PATH` comes
from. The named volume holds one stale `config.php` and nothing else.

Consequences that matter to this repo:

- Anything backing up "the files volume" on the old host backs up 124 bytes.
- Anonymous volumes are dropped by some container recreations. Six orphans are
  on that disk; one still holds `250925_Mitglieder.xlsx`, a member export
  detached in 2025 whose `adm_files` row went with it.
- VM 317 mounts a **named** volume at the correct path, so uploads survive a
  `docker compose up --force-recreate` and are actually backed up.

### Database backup

`backup-scheduler` runs as a systemd *user* service **on the jump box (VM 230)**,
not on either database host:

```bash
systemctl --user status st-andreas-backup     # enabled; dumps at 02:00 Europe/Berlin
ls -lt ~/DEV/st-andreas/backups | head        # admidio_YYYYMMDD_HHMMSS.sql.gz, 30-day retention
```

It follows `HETZNER_SSH_HOST`, so **do not flip those keys before cutover** --
it would start backing up the empty standby while the live host goes uncovered.

VM 317 additionally runs its own nightly job at 03:30 (`st-andreas-backup.timer`)
that dumps the database *and* tars the documents volume to
`/srv/st-andreas-backups`, plus a Proxmox Backup Server snapshot every two
hours. The old host has neither.

### Verifying a host switch

```bash
# 1. the tunnel and the query path
uv run python -c "
from st_andreas.admidio_db import ssh_tunnel, db_connection
with ssh_tunnel(), db_connection() as c:
    with c.cursor() as k:
        k.execute('SELECT COUNT(*) FROM adm_users'); print('users:', k.fetchone()[0])"

# 2. the upload path -- lands as www-data and is visible to the app
uv run fetch-members-all
```

Expect **294** users, 291 with an IBAN, 5 rows in `adm_files`. Both paths were
verified against VM 317 on 2026-09-03.
