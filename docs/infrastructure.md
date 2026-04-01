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
