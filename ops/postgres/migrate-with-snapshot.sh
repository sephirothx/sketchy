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
# readable only by this user (it is the whole database), prints the command
# that restores it, and only then runs the migration. A failed dump stops the
# deploy: no snapshot, no migration.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
backend="$here/../../backend"
bin="${PG_BIN:+$PG_BIN/}"
: "${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL must name the schema owner}"
dir="${SNAPSHOT_DIR:?SNAPSHOT_DIR must name where the snapshot goes}"

# The owner's password never goes on a command line, where any local user
# can read it from the process list for as long as the dump runs. SQLAlchemy
# splits the URL (percent-encoding and all, and the driver suffix libpq does
# not know); the password goes to a passfile only this user can read, and the
# rest to libpq's environment variables.
umask 077
passfile="$(mktemp)"
trap 'rm -f "$passfile"' EXIT
IFS=$'\t' read -r PGHOST PGPORT PGUSER PGDATABASE PGSSLMODE < <(
  PASSFILE="$passfile" "$backend/.venv/bin/python" - <<'PY'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["MIGRATION_DATABASE_URL"])
host, port = url.host or "localhost", str(url.port or 5432)
user, database = url.username or "", url.database or ""


def field(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


# libpq's order: hostname:port:database:username:password.
with open(os.environ["PASSFILE"], "w", encoding="utf-8") as handle:
    handle.write(":".join(field(value) for value in (host, port, database, user, url.password or "")) + "\n")
print("\t".join((host, port, user, database, str(url.query.get("sslmode", "prefer")))))
PY
)
[[ -n "$PGDATABASE" ]] || { echo "MIGRATION_DATABASE_URL names no database" >&2; exit 1; }
export PGHOST PGPORT PGUSER PGDATABASE PGSSLMODE PGPASSFILE="$passfile"

revision="$("${bin}psql" -XAtc "SELECT version_num FROM alembic_version" 2>/dev/null || echo none)"
mkdir -p "$dir"
file="$dir/sketchy-$(date -u +%Y%m%dT%H%M%SZ)-${revision}.dump"

"${bin}pg_dump" --format=custom --no-owner --file="$file"
echo "snapshot: $file ($(du -h "$file" | cut -f1), revision $revision)"
echo "to restore, as the owner with its password in ~/.pgpass:"
echo "  ${bin}pg_restore --clean --if-exists --no-owner --host=$PGHOST --port=$PGPORT --username=$PGUSER --dbname=$PGDATABASE \"$file\""

cd "$backend"
.venv/bin/python -m app.db.migrate
