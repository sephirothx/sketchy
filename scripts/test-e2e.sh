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

# Pre-flight port check
existing_pid="$(lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$existing_pid" ]]; then
  log "Port $PORT is in use by PID $existing_pid - stopping server to run clean E2E tests"
  kill $existing_pid 2>/dev/null || true
  sleep 1
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
(cd "$BACKEND_DIR" && DATABASE_URL="sqlite+aiosqlite:///$E2E_DB" \
  AUTH_LOGIN_LIMIT=1000 AUTH_REGISTER_LIMIT=1000 AUTH_LOOKUP_LIMIT=1000 \
  TURN_RESULTS_SECONDS=0.5 RESTART_DELAY_SECONDS=0.25 \
  "$BACKEND_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning) >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    if [[ "$STARTUP_FAILED" == false ]]; then
      log "Stopping background server (PID: $SERVER_PID)"
    fi
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$SERVER_LOG"
  [[ -n "${E2E_DB:-}" ]] && rm -f "$E2E_DB"
}
trap cleanup EXIT

# Wait for the API health check while also watching for an early server exit.
log "Waiting for server startup..."
server_healthy=false
for i in {1..30}; do
  if curl --fail --silent "http://127.0.0.1:$PORT/api/health" >/dev/null; then
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

log "Running Playwright Multi-Browser E2E Tests ($E2E_WORKERS workers)"
# --dist=load spreads individual tests rather than whole files, so one slow file
# no longer sets the floor for the whole run. Each test builds its own room and
# its own browser, so nothing in a file depends on its neighbours.
(cd "$BACKEND_DIR" && .venv/bin/pytest tests/e2e -n "$E2E_WORKERS" --dist=load)
