#!/usr/bin/env bash
# The Compose smoke (#405): build the image, bring the production stack up on
# an empty directory, and prove from outside that it is a working deployment,
# across a full restart.
#
#   ops/compose/smoke/smoke.sh
#
# Needs Docker with Compose v2, and backend/.venv (requirements-dev.txt) for
# the probe and the game driver, which run on this host like any player.
# Touches nothing but a temporary directory and a Compose project of its own
# (sketchy-smoke-<pid>), both removed at the end; KEEP=1 leaves them up.
#
# What it checks, in order:
#   1. the base compose file publishes no port (only the tunnel reaches the app)
#   2. the cluster was created with checksums, the tracked config and the
#      three roles, and the application role cannot create a table (#896)
#   3. the migration took a snapshot first, and the database is at the one
#      Alembic head
#   4. the app started in production mode with the bundled prompt lists seeded
#   5. the page, readiness and /metrics (refused without its token) answer
#      through the proxy
#   6. the synthetic probe plays a stroke (app.probe)
#   7. games are played to the end and written to history (benchmarks/load.py
#      --finish-games), drawings included
#   8. an account registers, its confirmation mail reaches the relay, it
#      exports its data and deletes itself (account.py)
#   9. after stopping and starting the whole stack: a second snapshot, the
#      same history, every stored drawing verifies, the probe still plays
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
compose_dir="$(cd "$here/.." && pwd)"
root="$(cd "$compose_dir/../.." && pwd)"
python="$root/backend/.venv/bin/python"
[[ -x "$python" ]] || { echo "backend/.venv is missing: see README → Running tests" >&2; exit 2; }

work="$(mktemp -d)"
project="sketchy-smoke-$$"
http_port="${SMOKE_HTTP_PORT:-18080}"
mail_port="${SMOKE_MAIL_PORT:-18025}"
base="http://127.0.0.1:$http_port"
secret() { openssl rand -hex 32; }

mkdir -p "$work/data/snapshots"
metrics_token="$(secret)"
cat >"$work/smoke.env" <<EOF
COMPOSE_PROFILES=
SKETCHY_IMAGE=sketchy:smoke
SKETCHY_DATA_DIR=$work/data
SKETCHY_UID=$(id -u)
SKETCHY_GID=$(id -g)
POSTGRES_SUPERUSER_PASSWORD=$(secret)
SKETCHY_OWNER_DB_PASSWORD=$(secret)
SKETCHY_APP_DB_PASSWORD=$(secret)
PUBLIC_BASE_URL=https://sketchy-smoke.org
CONTACT_ADDRESS=privacy@sketchy-smoke.org
IP_HASH_SECRET=$(secret)
METRICS_TOKEN=$metrics_token
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_SECURITY=none
SMTP_FROM=Sketchy <play@sketchy-smoke.org>
SMOKE_HTTP_PORT=$http_port
SMOKE_MAIL_PORT=$mail_port
SKETCHY_COMMIT_SHA=$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo unknown)
EOF
app_password="$(grep '^SKETCHY_APP_DB_PASSWORD=' "$work/smoke.env" | cut -d= -f2)"

dc() { docker compose --project-name "$project" --env-file "$work/smoke.env" --project-directory "$compose_dir" -f "$compose_dir/compose.yaml" -f "$here/compose.smoke.yaml" "$@"; }
base_only() { docker compose --project-name "$project" --env-file "$work/smoke.env" -f "$compose_dir/compose.yaml" "$@"; }
sql() { dc exec -T db psql -X -v ON_ERROR_STOP=1 -U postgres -d sketchy -Atc "$1"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }

cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    echo "--- logs (the run failed) ---" >&2
    dc logs --no-color --tail=200 >&2 || true
  fi
  if [[ "${KEEP:-}" == 1 ]]; then
    echo "KEEP=1: project $project and $work left in place" >&2
    return
  fi
  dc down --volumes --remove-orphans >/dev/null 2>&1 || true
  # The cluster's files belong to the container's postgres user, not to us.
  docker run --rm -v "$work/data:/data" postgres:17.11-trixie rm -rf /data/postgres >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

# Waits for a URL to answer 200, up to $2 seconds.
wait_for() {
  local deadline=$((SECONDS + $2))
  until curl -fsS -o /dev/null "$1" 2>/dev/null; do
    (( SECONDS < deadline )) || fail "$1 did not answer 200 within $2 s"
    sleep 2
  done
}

migrate_exit_code() {
  docker inspect -f '{{.State.ExitCode}}' "$(dc ps --all --quiet migrate | head -1)"
}

# --- 1. nothing published --------------------------------------------------
published="$(base_only config --format json | "$python" -c '
import json, sys
services = json.load(sys.stdin)["services"]
print(" ".join(name for name, service in services.items() if service.get("ports")))
')"
[[ -z "$published" ]] || fail "the base compose file publishes ports for: $published"
ok "the base compose file publishes no port"

BUILDKIT_PROGRESS=plain dc build
dc up -d
wait_for "$base/api/ready" 240
[[ "$(migrate_exit_code)" == 0 ]] || fail "the migration did not exit 0"

# --- 2. the cluster ------------------------------------------------------------
[[ "$(sql 'SHOW data_checksums')" == on ]] || fail "data checksums are off"
[[ "$(sql 'SHOW shared_preload_libraries')" == *pg_stat_statements* ]] || fail "sketchy.conf was not included"
[[ "$(sql "SELECT count(*) FROM pg_roles WHERE rolname IN ('sketchy_owner', 'sketchy_app', 'sketchy_monitor')")" == 3 ]] \
  || fail "the three roles are not all there"
if dc exec -T -e PGPASSWORD="$app_password" db psql -X -h 127.0.0.1 -U sketchy_app -d sketchy -c "CREATE TABLE smoke_probe (i int)" >/dev/null 2>&1; then
  fail "sketchy_app can create a table"
fi
ok "cluster: checksums on, sketchy.conf included, roles in place, the app role cannot create a table"

# --- 3. snapshot and head ------------------------------------------------------
snapshots() { find "$work/data/snapshots" -name 'sketchy-*.dump' | wc -l | tr -d ' '; }
[[ "$(snapshots)" == 1 ]] || fail "expected one snapshot before the first migration, found $(snapshots)"
heads="$(dc run --rm --no-deps -T migrate alembic heads)"
[[ "$(grep -c '(head)' <<<"$heads")" == 1 ]] || fail "expected exactly one Alembic head: $heads"
head="${heads%% *}"
[[ "$(sql 'SELECT version_num FROM alembic_version')" == "$head" ]] || fail "the database is not at head $head"
ok "snapshot taken before migrating; database at the one head ($head)"

# --- 4. production, seeded -------------------------------------------------------
# Two things only production does: keep the API docs unserved (#1418), and
# let crawlers in everywhere but rooms (R-SEO-02).
[[ "$(curl -s -o /dev/null -w '%{http_code}' "$base/docs")" == 404 ]] || fail "/docs is served: not production"
if curl -fsS "$base/robots.txt" | grep -qx 'Disallow: /'; then
  fail "robots.txt disallows everything: not production"
fi
lists="$(sql 'SELECT count(*) FROM prompt_lists')"
(( lists > 0 )) || fail "no prompt lists were seeded"
ok "app in production mode, $lists prompt lists seeded"

# --- 5. through the proxy --------------------------------------------------------
curl -fsS "$base/" | grep -q '<div id="root"' || fail "/ did not serve the app's page"
[[ "$(curl -s -o /dev/null -w '%{http_code}' "$base/metrics")" == 401 ]] || fail "/metrics answered without its token"
curl -fsS -H "Authorization: Bearer $metrics_token" "$base/metrics" | grep -q '^sketchy_' || fail "/metrics did not answer with the token"
ok "page, readiness and /metrics answer through the proxy"

# --- 6. probe --------------------------------------------------------------------
(cd "$root/backend" && "$python" -m app.probe --base-url "$base" --no-state) || fail "the probe failed"
ok "the probe played"

# --- 7. games to the end -----------------------------------------------------------
# The load harness is the driver here, not a gate: its latency thresholds
# are for the reference machine (#461), and a CI runner breaching one says
# nothing about the deployment. What it must have done is checked below.
"$python" "$root/benchmarks/load.py" --base-url "$base" --rooms 1 --seats 3 --lobby-watchers 1 \
  --slow-viewers 0 --reconnect-share 0 --duration 75 --finish-games --shared-address \
  --metrics-token "$metrics_token" --json-output "$work/load.json" >"$work/load.log" 2>&1 \
  || echo "note: load.py reported breaches; functional results are judged below (log: load.log)"
"$python" - "$work/load.json" <<'PY' || { cat "$work/load.log" >&2; fail "games were not played to the end and written"; }
import json, sys
measured = json.load(open(sys.argv[1]))["measured"]
wanted = {
    "historyGamesWritten": lambda v: v >= 1,
    "roomsWithoutAFinishedGame": lambda v: v == 0,
    "historyGamesUnwritten": lambda v: v == 0,
    "historyWritesAbandoned": lambda v: v == 0,
    "drawFramesAccepted": lambda v: v >= 1,
    "unexpectedDisconnects": lambda v: v == 0,
    "faultNotices": lambda v: v == 0,
}
wrong = {key: measured.get(key) for key, good in wanted.items() if measured.get(key) is None or not good(measured[key])}
print("load:", {key: measured.get(key) for key in wanted})
sys.exit(1 if wrong else 0)
PY
games="$(sql 'SELECT count(*) FROM game_records')"
drawings="$(sql 'SELECT count(*) FROM turn_drawings')"
(( games > 0 && drawings > 0 )) || fail "history holds $games games and $drawings drawings"
ok "$games games and $drawings drawings in history"

# --- 8. an account ---------------------------------------------------------------
python3 "$here/account.py" --base-url "$base" --mail-api "http://127.0.0.1:$mail_port" || fail "the account flow failed"

# --- 9. restart --------------------------------------------------------------------
dc stop
dc up -d
wait_for "$base/api/ready" 240
[[ "$(migrate_exit_code)" == 0 ]] || fail "the migration did not exit 0 after the restart"
[[ "$(snapshots)" == 2 ]] || fail "expected a second snapshot after the restart, found $(snapshots)"
[[ "$(sql 'SELECT count(*) FROM game_records')" == "$games" ]] || fail "history changed across the restart"
[[ "$(sql 'SELECT count(*) FROM turn_drawings')" == "$drawings" ]] || fail "drawings changed across the restart"
dc exec -T app python -m app.services.drawing_storage || fail "a stored drawing failed verification"
(cd "$root/backend" && "$python" -m app.probe --base-url "$base" --no-state) || fail "the probe failed after the restart"
ok "after a full restart: second snapshot, history intact, every drawing verifies, the probe plays"

echo "smoke passed"
