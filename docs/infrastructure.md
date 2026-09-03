# Infrastructure Access Guide

## Hetzner Server (Admidio)

### SSH Access

**Host:** `91.98.90.85`  
**User:** `root`  
**Hostname:** `ubuntu-sta`

#### SSH Key Setup

The SSH private key should be stored at `~/.ssh/hetzner_key` with permissions `600`.

```bash
# Connect to Hetzner server
ssh -i ~/.ssh/hetzner_key root@91.98.90.85
```

#### Key Contents

If you need to set up access on a new machine, the SSH key (Ed25519) is associated with `johannes@langhein.net`. Request the key from the administrator and save it:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
# Paste key content into ~/.ssh/hetzner_key
chmod 600 ~/.ssh/hetzner_key
```

---

## Admidio Database (MariaDB)

Admidio runs in Docker on the Hetzner server.

### Connection Details

| Setting | Value |
|---------|-------|
| Type | MariaDB 10.11 |
| Host (Docker internal) | `db` |
| Port | `3306` |
| Database | `admidio` |
| User | `admidio` |
| Table Prefix | `adm_` |

### Accessing the Database

#### Option 1: SSH Tunnel

Create an SSH tunnel to access the database from your local machine:

```bash
# Create tunnel (forwards local port 3307 to MariaDB)
ssh -i ~/.ssh/hetzner_key -L 3307:localhost:3306 root@91.98.90.85 -N &

# Connect via mysql client
mysql -h 127.0.0.1 -P 3307 -u admidio -p admidio
```

#### Option 2: Docker Exec

SSH into the server and access the database via Docker:

```bash
ssh -i ~/.ssh/hetzner_key root@91.98.90.85

# Access MariaDB via Docker
docker exec -it admidio_db mysql -u admidio -p admidio
```

#### Option 3: phpMyAdmin

phpMyAdmin is available at: `http://91.98.90.85:8081`

- User: `admidio` or `root`
- Use corresponding password from `secrets.env`

### URLs

- **Admidio Web App:** https://sta.hg-hausverwalter.de
- **phpMyAdmin:** http://91.98.90.85:8081

---

## Internal Server

### SSH Access

**Host:** `10.10.10.18`  
**User:** `administrator`  
**Auth:** Password-based (see `secrets.env`)

```bash
# Requires sshpass for password auth
sshpass -p '<password>' ssh administrator@10.10.10.18
```

---

## Environment Files

- **secrets.env** - Contains all credentials (DO NOT commit to git)
- Ensure `secrets.env` is in `.gitignore`

## Security Notes

1. Never commit `secrets.env` to version control
2. SSH keys should have `600` permissions
3. Rotate passwords periodically
4. Restrict phpMyAdmin access if possible (currently on public port)

---

## Admidio Update Procedure (patched German wording)

The German UI is served from a **derived image**: `docker/Dockerfile.admidio` starts from
the Admidio image **pinned by digest** and rewrites `de-DE.xml` and `de.xml` to the
generic masculine at build time with `tools/degender.py`. `adm_program` is not a Docker
volume, so a plain `docker compose pull` throws the wording away — the rebuild is part
of the update, not an optional extra.

The target host is **Oerenburg VM 317**, which pins Admidio by digest in its own
`docker-compose.yml`. `docker/Dockerfile.admidio` names the same digest:

```
admidio/admidio@sha256:bd24f79a38ff2163ff4bc465792f3f3d7113a799dc91a770c26aaf82d66a1f88   # 4.3.16
```

That is deliberate. The derived image is a **pure wording patch on the exact bits VM 317
runs**: deploying it changes no Admidio version, so a wording change can never smuggle in
an upgrade. The 4.3.16 tag no longer exists on Docker Hub — the digest is the only way to
reach that build, and it is also what makes it reproducible. The old Hetzner box still
runs `admidio/admidio:latest` (pulled once in 2025, also 4.3.16) and stays unpinned until
the DNS cutover.

### Rebuilding after a change to the transform

```bash
docker build -f docker/Dockerfile.admidio -t admidio-sta:4.3.16 .
```

Run this from the repository root — the build needs `tools/degender.py` in the context.
The base digest comes from the `ADMIDIO_IMAGE` default in the Dockerfile; do not pass a
different one just to make a build succeed.

### Updating Admidio itself

**A version bump is an edit to the digest, not a side effect.** A tag can move under you
between two pulls; a digest cannot, which is the whole point of the pin.

1. Decide on the new Admidio version and agree it with whoever runs VM 317 — the host's
   `docker-compose.yml` and this Dockerfile must name the **same** digest, or the review
   stack and production run different code.

2. Resolve the digest for the new tag and put it in `docker/Dockerfile.admidio`:
   ```bash
   docker buildx imagetools inspect admidio/admidio:v4.3.18 --format '{{.Manifest.Digest}}'
   ```

3. Rebuild. The transform prints one line per file plus every waived string. If it reports
   `UNRESOLVED`, the new Admidio version reworded a string and the build fails on purpose:
   add a rule to `CONTEXT_RULES` (or a token to `TOKEN_REPLACEMENTS`) in
   `tools/degender.py`, extend `tests/test_degender.py`, rebuild. `STALE RULE` lines are
   informational — they mean upstream dropped a phrase we rewrite.

4. For an urgent security update that must not wait for a wording fix, add the string id
   to `ACCEPTED_STRINGS` with a reason. The waiver is printed on every later build, so it
   stays visible until it is removed.

5. Review the result locally (see `docker-compose.dev.yml` and
   `scripts/admidio-dev-stack.sh`), then deploy the image and update the host's pin.

6. Recreate the container and confirm the wording survived, for example by loading
   `https://sta.hg-hausverwalter.de` and checking that no `:innen` form is visible. A
   version bump also needs Admidio's own database update run afterwards.

### Fallback if the rebuild is ever unwelcome

Run the transform against the running container after every recreate:

```bash
docker cp tools/degender.py admidio:/tmp/degender.py
docker exec admidio python3 /tmp/degender.py \
  /opt/app-root/src/adm_program/languages/de-DE.xml \
  /opt/app-root/src/adm_program/languages/de.xml
```

The official image has no Python interpreter, so this needs one installed in the
container first. It also leaves the UI unpatched between a recreate and the next run.

---

## Database Backups

### Overview

Automated daily backups run at 02:00 Europe/Berlin time. Backups are stored locally in the `backups/` directory and compressed with gzip.

### Configuration

Optional settings in `secrets.env`:

```bash
BACKUP_DIR=./backups           # Default: ./backups
BACKUP_RETENTION_DAYS=30       # Default: 30
BACKUP_TIME_HOUR=2             # Default: 2 (2 AM)
BACKUP_TIME_MINUTE=0           # Default: 0
BACKUP_TIMEZONE=Europe/Berlin  # Default: Europe/Berlin
```

### Running the Backup Scheduler

```bash
# Start scheduler (runs continuously, executes backup at scheduled time)
uv run backup-scheduler

# Run single backup immediately (for testing)
uv run backup-scheduler --once
```

### Manual Backup via SSH

```bash
ssh -i ~/.ssh/hetzner_key root@91.98.90.85 \
  "docker exec admidio_db mysqldump -u root -p<password> admidio" \
  | gzip > backups/admidio_manual_$(date +%Y%m%d_%H%M%S).sql.gz
```

### Restoring from Backup

```bash
# Decompress and restore
gunzip -c backups/admidio_20250401_020000.sql.gz | \
  ssh -i ~/.ssh/hetzner_key root@91.98.90.85 \
  "docker exec -i admidio_db mysql -u root -p<password> admidio"
```

### Backup Files

- **Location:** `backups/` directory (gitignored)
- **Naming:** `admidio_YYYYMMDD_HHMMSS.sql.gz`
- **Retention:** Configurable, default 30 days
