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

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

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
(cd "$FRONTEND_DIR" && VITE_SERVER_URL="http://127.0.0.1:$PORT" npm run build --silent)

# Start background server
log "Starting background server on http://127.0.0.1:$PORT"
(cd "$BACKEND_DIR" && "$BACKEND_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning) &
SERVER_PID=$!

cleanup() {
  log "Stopping background server (PID: $SERVER_PID)"
  kill $SERVER_PID 2>/dev/null || true
}
trap cleanup EXIT

# Wait for server to respond on port
log "Waiting for server startup..."
for i in {1..30}; do
  if curl -s "http://127.0.0.1:$PORT" >/dev/null; then
    break
  fi
  sleep 0.5
done

log "Running Playwright Multi-Browser E2E Tests"
(cd "$BACKEND_DIR" && .venv/bin/pytest tests/e2e -v)
