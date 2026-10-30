#!/usr/bin/env bash
# First-start setup for the db service (#405), run once by the postgres
# image's entrypoint, when it creates the cluster and never again. Does on a
# fresh container what docs/database.md → Server configuration does by hand:
#
#   1. include the tracked config (ops/postgres/sketchy.conf, mounted
#      read-only), so a later edit takes effect on the next restart;
#   2. run ops/postgres/init.sql: the extension and the three roles (#896);
#   3. give the roles their passwords from the environment.
#
# psql reads the passwords from its own environment (\getenv), never from
# its command line, where any process on the host could read them.
set -euo pipefail

echo "include '/etc/postgresql/sketchy.conf'" >>"$PGDATA/postgresql.conf"

psql=(psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")
"${psql[@]}" -q -f /opt/sketchy/init.sql

"${psql[@]}" -q <<'SQL'
\getenv owner_password SKETCHY_OWNER_DB_PASSWORD
\getenv app_password SKETCHY_APP_DB_PASSWORD
ALTER ROLE sketchy_owner PASSWORD :'owner_password';
ALTER ROLE sketchy_app PASSWORD :'app_password';
SQL

# The monitor role is postgres_exporter's, which arrives with the monitoring
# stack. Until it has a password it cannot sign in at all.
if [[ -n "${SKETCHY_MONITOR_DB_PASSWORD:-}" ]]; then
  "${psql[@]}" -q <<'SQL'
\getenv monitor_password SKETCHY_MONITOR_DB_PASSWORD
ALTER ROLE sketchy_monitor PASSWORD :'monitor_password';
SQL
fi
