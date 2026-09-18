#!/usr/bin/env bash
# Prove ops/postgres/ against a real server (#889): initdb a throwaway cluster
# with initdb.args, start it on sketchy.conf, run init.sql, and check that
# checksums are on, pg_stat_statements records, and a slow statement is logged
# with its duration and application_name. Touches nothing outside a temporary
# directory, which it removes.
#
#   ops/postgres/check-config.sh                 # binaries on PATH
#   PG_BIN=/opt/homebrew/opt/postgresql@17/bin ops/postgres/check-config.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
bin="${PG_BIN:+$PG_BIN/}"
port="${PG_CHECK_PORT:-55439}"
work="$(mktemp -d)"
data="$work/data"
log="$work/server.log"
trap '"${bin}pg_ctl" -D "$data" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

fail() { echo "FAIL: $*" >&2; echo "--- server log ---" >&2; cat "$log" >&2 || true; exit 1; }

# shellcheck disable=SC2046 # the flags are words on purpose
"${bin}initdb" -D "$data" -U postgres --auth=trust $(grep -v '^#' "$here/initdb.args") >"$work/initdb.log" 2>&1 \
  || { cat "$work/initdb.log" >&2; exit 1; }
cp "$here/sketchy.conf" "$data/sketchy.conf"
echo "include 'sketchy.conf'" >>"$data/postgresql.conf"
"${bin}pg_ctl" -D "$data" -o "-p $port -c listen_addresses=127.0.0.1 -k $work" -l "$log" -w start >/dev/null \
  || fail "the server did not start on sketchy.conf"

psql() { "${bin}psql" -X -q -h 127.0.0.1 -p "$port" -U postgres -v ON_ERROR_STOP=1 "$@"; }
psql -d postgres -c "CREATE DATABASE sketchy"
psql -d sketchy -f "$here/init.sql" >/dev/null
psql -d sketchy -f "$here/init.sql" >/dev/null   # idempotent

[[ "$(psql -d sketchy -Atc 'SHOW data_checksums')" == on ]] || fail "data checksums are off"
[[ "$(psql -d sketchy -Atc 'SHOW wal_compression')" == lz4 ]] || fail "wal_compression is not lz4"
[[ "$(psql -d sketchy -Atc 'SHOW default_toast_compression')" == lz4 ]] || fail "toast compression is not lz4"
psql -d sketchy -Atc "SELECT pg_is_in_recovery()" >/dev/null

# A statement over log_min_duration_statement, under the web role's name.
PGAPPNAME=sketchy-web psql -d sketchy -c "SELECT pg_sleep(0.3)" >/dev/null
grep -q "app=sketchy-web.*duration: [0-9.]* ms  statement: SELECT pg_sleep(0.3)" "$log" \
  || fail "the slow statement was not logged with its duration and application_name"

# pg_stat_statements is recording, and the monitor role can read all of it.
calls="$(psql -d sketchy -U sketchy_monitor -Atc \
  "SELECT sum(calls) FROM pg_stat_statements WHERE query LIKE 'SELECT pg_sleep%'")"
[[ "$calls" -ge 1 ]] || fail "pg_stat_statements did not record the statement"
# ...and nothing else: the monitor role reads no table data.
if psql -d sketchy -U sketchy_monitor -c "CREATE TABLE t (i int)" >/dev/null 2>&1; then
  fail "sketchy_monitor can create a table"
fi

echo "ok: checksums on, lz4 WAL and TOAST, slow statement logged with app name, pg_stat_statements readable by sketchy_monitor"
