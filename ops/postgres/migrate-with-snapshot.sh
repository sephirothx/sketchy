#!/usr/bin/env bash
# Take a snapshot, then migrate (#893). The recovery from a bad release is to
# restore and fix forward (#458) - migrations are not trusted to run backwards
# over live rows - and a restore needs something taken immediately before the
# change, not last night's backup plus a day of games.
#
#   MIGRATION_DATABASE_URL=postgresql+asyncpg://sketchy_owner:...@db:5432/sketchy \
#   SNAPSHOT_DIR=/srv/sketchy/snapshots \
#     ops/postgres/migrate-with-snapshot.sh
#
# Writes one custom-format dump named for the time and the revision it holds,
# prints the command that restores it, and only then runs the migration. A
# failed dump stops the deploy: no snapshot, no migration.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
backend="$here/../../backend"
bin="${PG_BIN:+$PG_BIN/}"
: "${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL must name the schema owner}"
dir="${SNAPSHOT_DIR:?SNAPSHOT_DIR must name where the snapshot goes}"

# libpq does not know SQLAlchemy's driver suffix.
url="${MIGRATION_DATABASE_URL/postgresql+asyncpg:/postgresql:}"
revision="$("${bin}psql" "$url" -XAtc "SELECT version_num FROM alembic_version" 2>/dev/null || echo none)"
mkdir -p "$dir"
file="$dir/sketchy-$(date -u +%Y%m%dT%H%M%SZ)-${revision}.dump"

"${bin}pg_dump" --format=custom --no-owner --file="$file" "$url"
echo "snapshot: $file ($(du -h "$file" | cut -f1), revision $revision)"
echo "to restore: ${bin}pg_restore --clean --if-exists --no-owner --dbname=\"<owner url>\" \"$file\""

cd "$backend"
.venv/bin/python -m app.db.migrate
