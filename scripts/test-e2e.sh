#!/usr/bin/env bash
# E2E Multi-Browser Test Runner Script
# Builds frontend, starts background server, runs Playwright E2E tests, and cleans up.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
VENV_PIP="$BACKEND_DIR/.venv/bin/pip"
PORT="${PORT:-8000}"
# Playwright work is mostly browser processes waiting on the server, so more
# workers than cores just adds contention and makes timing-sensitive tests
# flake. Cap at 8: measured stable here, and CI boxes with fewer cores get
# their own count.
cpu_count="$( (sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null) || echo 2)"
E2E_WORKERS="${E2E_WORKERS:-$(( cpu_count > 8 ? 8 : cpu_count ))}"
# CI runs this script once per shard, on a runner of its own. Everything the
# shard needs is decided in tests/e2e/conftest.py; the two variables only have
# to reach pytest, and default to "the whole suite" so a local run is unchanged.
E2E_SHARD_COUNT="${E2E_SHARD_COUNT:-1}"
E2E_SHARD="${E2E_SHARD:-1}"
export E2E_SHARD_COUNT E2E_SHARD
SERVER_LOG=""
E2E_DB=""
SERVER_PID=""
STARTUP_FAILED=false

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

server_log_summary() {
  local summary
  summary="$(awk 'NF { line=$0 } END { print line }' "$SERVER_LOG")"
  summary="${summary//$'\r'/}"
  summary="${summary//$'\n'/ }"
  printf '%.240s' "$summary"
}

fail_startup() {
  local reason="$1"
  local detail
  detail="$(server_log_summary)"
  STARTUP_FAILED=true
  if [[ -n "$detail" ]]; then
    printf 'E2E server startup failed: %s (last log: %s)\n' "$reason" "$detail" >&2
  else
    printf 'E2E server startup failed: %s\n' "$reason" >&2
  fi
  exit 1
}

port_listeners() {
  lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

# Wait for the port to come free, escalating to SIGKILL. Bounded, and the
# caller decides what an unfree port means.
release_port() {
  local waited=0
  while [[ -n "$(port_listeners)" ]]; do
    if (( waited == 20 )); then
      kill -9 $(port_listeners) 2>/dev/null || true
    fi
    if (( waited >= 40 )); then
      return 1
    fi
    kill $(port_listeners) 2>/dev/null || true
    sleep 0.25
    waited=$(( waited + 1 ))
  done
  return 0
}

# Pre-flight port check. This has to hold before the server starts, not just be
# attempted: a leftover server that survives keeps the port, the new one fails
# to bind and exits, and the readiness check below is then answered by the old
# process - so the whole suite runs against a stale build and fails in ways
# that look like broken code.
if [[ -n "$(port_listeners)" ]]; then
  log "Port $PORT is in use by PID $(port_listeners | tr '\n' ' ')- stopping it to run clean E2E tests"
  release_port || {
    printf 'E2E server startup failed: port %s is still held by PID %s\n' \
      "$PORT" "$(port_listeners | tr '\n' ' ')" >&2
    exit 1
  }
fi

# The frontend talks to /api and /socket.io relative to whatever origin served
# it, and that origin is this same server, so the build needs no server URL.
log "Building frontend for E2E tests"
(cd "$FRONTEND_DIR" && VITE_RENDER_DIAGNOSTICS="true" npm run build --silent)

# Start background server
SERVER_LOG="$(mktemp "${TMPDIR:-/tmp}/sketchy-e2e-server.XXXXXX")"
# Usernames are permanently unique, so a database carried over from a previous
# run would make account tests collide on the second run. Each run gets its own
# throwaway database, removed on exit.
E2E_DB="$(mktemp "${TMPDIR:-/tmp}/sketchy-e2e-db.XXXXXX")"
rm -f "$E2E_DB"
log "Starting background server on http://127.0.0.1:$PORT"
# `exec` so the subshell *becomes* the server: without it `$!` is the
# subshell, killing that leaves the real process holding the port, and the
# next run inherits a server serving the previous build.
(cd "$BACKEND_DIR" && exec env DATABASE_URL="sqlite+aiosqlite:///$E2E_DB" \
  AUTH_LOGIN_LIMIT=1000 AUTH_REGISTER_LIMIT=1000 AUTH_LOOKUP_LIMIT=1000 \
  GUEST_PROVISION_LIMIT=1000 GUEST_PROVISION_DAILY_LIMIT=100000 \
  TURN_RESULTS_SECONDS=0.5 SHUTDOWN_DRAIN_SECONDS=0 LOG_LEVEL=warning \
  "$BACKEND_DIR/.venv/bin/python" -m app.server) >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    if [[ "$STARTUP_FAILED" == false ]]; then
      log "Stopping background server (PID: $SERVER_PID)"
    fi
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    # Anything still on the port is this run's doing, and leaving it there is
    # what makes the *next* run mysterious rather than this one.
    release_port || printf 'Warning: port %s is still held by PID %s\n' \
      "$PORT" "$(port_listeners | tr '\n' ' ')" >&2
  fi
  rm -f "$SERVER_LOG"
  [[ -n "${E2E_DB:-}" ]] && rm -f "$E2E_DB"
}
trap cleanup EXIT

# Wait for application readiness while also watching for an early server exit.
log "Waiting for server startup..."
server_healthy=false
for i in {1..30}; do
  if curl --fail --silent "http://127.0.0.1:$PORT/api/ready" >/dev/null; then
    server_healthy=true
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    server_status=0
    wait "$SERVER_PID" || server_status=$?
    SERVER_PID=""
    fail_startup "server exited with status $server_status"
  fi
  sleep 0.5
done

if [[ "$server_healthy" == false ]]; then
  fail_startup "health check did not pass within 15 seconds"
fi

# The thing answering must be the thing we started. A 200 alone does not say
# that, and a stale server answering for us is the failure this whole run is
# least able to diagnose: every test fails against code nobody is looking at.
if ! port_listeners | grep -qx "$SERVER_PID"; then
  fail_startup "port $PORT is answering from PID $(port_listeners | tr '\n' ' ')rather than the server this run started ($SERVER_PID)"
fi

if (( E2E_SHARD_COUNT > 1 )); then
  log "Running Playwright Multi-Browser E2E Tests (shard $E2E_SHARD of $E2E_SHARD_COUNT, $E2E_WORKERS workers)"
else
  log "Running Playwright Multi-Browser E2E Tests ($E2E_WORKERS workers)"
fi
# --dist=load spreads individual tests rather than whole files, so one slow file
# no longer sets the floor for the whole run. Each test builds its own room and
# its own browser, so nothing in a file depends on its neighbours.
# The tests get the server's own database URL so a test that needs a staff
# account can promote one, rather than the suite carrying a back door for it.
(cd "$BACKEND_DIR" && SKETCHY_E2E_DATABASE_URL="sqlite+aiosqlite:///$E2E_DB" \
  .venv/bin/pytest tests/e2e -n "$E2E_WORKERS" --dist=load)
