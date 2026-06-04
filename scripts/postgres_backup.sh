#!/usr/bin/env bash

set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: DATABASE_URL=... POSTGRES_BACKUP_DIR=/secure/path bash scripts/postgres_backup.sh

Creates a PostgreSQL custom-format dump. Production backups must be encrypted
with BACKUP_ENCRYPTION=age or BACKUP_ENCRYPTION=gpg.

Required:
  DATABASE_URL
  POSTGRES_BACKUP_DIR or BACKUP_DIR

Encryption:
  BACKUP_ENCRYPTION=age with BACKUP_AGE_RECIPIENT
  BACKUP_ENCRYPTION=gpg with BACKUP_GPG_RECIPIENT
  BACKUP_ENCRYPTION=none is refused when APP_ENV=production
USAGE
  exit 0
fi

log() {
  printf '[postgres_backup] %s\n' "$1"
}

fail() {
  printf '[postgres_backup] %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

require_command pg_dump
require_command sha256sum

if [[ -z "${DATABASE_URL:-}" ]]; then
  fail "DATABASE_URL is required"
fi

backup_dir="${POSTGRES_BACKUP_DIR:-${BACKUP_DIR:-}}"
if [[ -z "$backup_dir" ]]; then
  fail "POSTGRES_BACKUP_DIR or BACKUP_DIR is required"
fi
if [[ "$backup_dir" == "/" || "$backup_dir" == "." ]]; then
  fail "backup directory must not be root or current directory"
fi
if [[ "${APP_ENV:-}" == "production" && "$backup_dir" != /* ]]; then
  fail "production backup directory must be an absolute path"
fi

umask 077
mkdir -p "$backup_dir"
chmod 700 "$backup_dir" 2>/dev/null || true

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
backup_name="${BACKUP_BASENAME:-deutsch_trainer}_${timestamp}.dump"
work_file="$(mktemp "${TMPDIR:-/tmp}/deutsch-trainer-backup.XXXXXX")"

cleanup() {
  rm -f "$work_file"
}
trap cleanup EXIT

log "creating PostgreSQL dump"
pg_dump \
  --dbname="$DATABASE_URL" \
  --format=custom \
  --no-owner \
  --no-acl \
  --file="$work_file"

encryption="${BACKUP_ENCRYPTION:-}"
if [[ -z "$encryption" ]]; then
  if [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
    encryption="age"
  elif [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
    encryption="gpg"
  else
    encryption="none"
  fi
fi

case "$encryption" in
  age)
    require_command age
    if [[ -z "${BACKUP_AGE_RECIPIENT:-}" ]]; then
      fail "BACKUP_AGE_RECIPIENT is required for age encryption"
    fi
    final_file="$backup_dir/$backup_name.age"
    age --recipient "$BACKUP_AGE_RECIPIENT" --output "$final_file" "$work_file"
    ;;
  gpg)
    require_command gpg
    if [[ -z "${BACKUP_GPG_RECIPIENT:-}" ]]; then
      fail "BACKUP_GPG_RECIPIENT is required for gpg encryption"
    fi
    final_file="$backup_dir/$backup_name.gpg"
    gpg --batch --yes --trust-model always --recipient "$BACKUP_GPG_RECIPIENT" --encrypt --output "$final_file" "$work_file"
    ;;
  none)
    if [[ "${APP_ENV:-}" == "production" ]]; then
      fail "unencrypted production backups are refused"
    fi
    final_file="$backup_dir/$backup_name"
    mv "$work_file" "$final_file"
    work_file=""
    ;;
  *)
    fail "BACKUP_ENCRYPTION must be age, gpg, or none"
    ;;
esac

sha256sum "$final_file" > "$final_file.sha256"
chmod 600 "$final_file" "$final_file.sha256" 2>/dev/null || true

if [[ "${BACKUP_RETENTION_DELETE_ENABLED:-false}" == "true" ]]; then
  retention_days="${BACKUP_RETENTION_DAYS:-7}"
  if ! [[ "$retention_days" =~ ^[0-9]+$ ]]; then
    fail "BACKUP_RETENTION_DAYS must be an integer"
  fi
  log "applying local retention policy"
  find "$backup_dir" -type f -name "${BACKUP_BASENAME:-deutsch_trainer}_*.dump*" -mtime +"$retention_days" -delete
fi

log "backup finished"
