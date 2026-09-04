#!/usr/bin/env bash
# Local Admidio review stack: build the patched image, seed a throwaway MariaDB
# from the newest backup, and serve it on 127.0.0.1 only.
#
#   scripts/admidio-dev-stack.sh up      build, start and seed (idempotent)
#   scripts/admidio-dev-stack.sh seed    re-import the newest backup
#   scripts/admidio-dev-stack.sh logins   list login names that exist in the copy
#   scripts/admidio-dev-stack.sh down    stop and delete both volumes

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.dev.yml"
ENV_FILE="${REPO_ROOT}/dev.env.local"
BACKUP_DIR="${BACKUP_DIR:-${REPO_ROOT}/backups}"
DEFAULT_PORT=8700

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

write_env_file_if_missing() {
  [[ -f "${ENV_FILE}" ]] && return 0
  echo "creating ${ENV_FILE} with generated passwords"
  umask 077
  cat >"${ENV_FILE}" <<EOF
# Local review stack only - gitignored, never used on a server.
ADMIDIO_DEV_PORT=${ADMIDIO_DEV_PORT:-${DEFAULT_PORT}}
ADMIDIO_DEV_DB_ROOT_PASSWORD=$(openssl rand -hex 16)
ADMIDIO_DEV_DB_PASSWORD=$(openssl rand -hex 16)
EOF
}

require_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo "${ENV_FILE} is missing, run '$0 up' first" >&2
    exit 1
  fi
  # shellcheck source=/dev/null
  set -a && source "${ENV_FILE}" && set +a
}

newest_backup() {
  local newest
  # Sorted by name, not mtime: the timestamp is zero-padded into the filename,
  # which survives a copy between hosts and needs no GNU-only find flags.
  newest="$(find "${BACKUP_DIR}" -maxdepth 1 -name 'admidio_*.sql.gz' | sort | tail -1)"
  if [[ -z "${newest}" ]]; then
    echo "no admidio_*.sql.gz in ${BACKUP_DIR}" >&2
    return 1
  fi
  echo "${newest}"
}

seed() {
  local dump
  dump="$(newest_backup)"
  echo "seeding from ${dump}"
  gunzip -c "${dump}" |
    compose exec -T db mariadb -u root -p"${ADMIDIO_DEV_DB_ROOT_PASSWORD}" admidio
  echo "seeded"
}

up() {
  write_env_file_if_missing
  require_env_file
  compose up -d --build
  seed
  # The seed replaces the tables under a running Admidio, so give it a fresh
  # connection before a human looks at it.
  compose restart admidio >/dev/null
  echo "Admidio is at http://127.0.0.1:${ADMIDIO_DEV_PORT:-${DEFAULT_PORT}}/adm_program/system/login.php"
}

logins() {
  require_env_file
  compose exec -T db mariadb -u root -p"${ADMIDIO_DEV_DB_ROOT_PASSWORD}" admidio \
    -e 'SELECT usr_login_name FROM adm_users WHERE usr_login_name IS NOT NULL ORDER BY usr_login_name;'
}

down() {
  require_env_file
  compose down --volumes --remove-orphans
  echo "stack removed including its volumes; ${ENV_FILE} kept"
}

case "${1:-up}" in
up) up ;;
seed)
  require_env_file
  seed
  ;;
logins) logins ;;
down) down ;;
*)
  echo "usage: $0 [up|seed|logins|down]" >&2
  exit 2
  ;;
esac
