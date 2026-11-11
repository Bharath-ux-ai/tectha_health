#!/usr/bin/env sh
# Nightly PostgreSQL backup with 14-day retention.
#   crontab:  15 2 * * *  /opt/tectha/deploy/backup.sh >> /var/log/tectha-backup.log 2>&1
# Restore:   gunzip -c backups/tectha-YYYYmmdd-HHMM.sql.gz | docker compose exec -T db psql -U tectha -d tectha
# Copy the backups directory off the server (S3, Google Drive, another VM). A backup on the same disk is not a backup.
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M)
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-tectha}" -d "${POSTGRES_DB:-tectha}" --no-owner --format=plain \
  | gzip -9 > "backups/tectha-$STAMP.sql.gz"
find backups -name 'tectha-*.sql.gz' -mtime +14 -delete
echo "Backup written: backups/tectha-$STAMP.sql.gz"
