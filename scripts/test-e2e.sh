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
SERVER_LOG=""
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

# Ensure frontend is built against the local E2E server (overrides
# frontend/.env.production.local, which may point at a Cloudflare tunnel).
log "Building frontend for E2E tests"
(cd "$FRONTEND_DIR" && VITE_SERVER_URL="http://127.0.0.1:$PORT" VITE_RENDER_DIAGNOSTICS="true" npm run build --silent)

# Start background server
SERVER_LOG="$(mktemp "${TMPDIR:-/tmp}/sketchy-e2e-server.XXXXXX")"
log "Starting background server on http://127.0.0.1:$PORT"
(cd "$BACKEND_DIR" && "$BACKEND_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning) >"$SERVER_LOG" 2>&1 &
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

log "Running Playwright Multi-Browser E2E Tests"
(cd "$BACKEND_DIR" && .venv/bin/pytest tests/e2e -v)
