#!/usr/bin/env bash
# Build the frontend, run the backend test suite, then start a single local
# server (backend on http://localhost:8000) that serves the built frontend
# as static files alongside the API/Socket.IO endpoints.
#
# Usage:
#   ./scripts/serve.sh              # build + test + serve
#   ./scripts/serve.sh --skip-tests # build + serve, skip pytest
#   ./scripts/serve.sh --skip-build # test + serve, reuse existing frontend/dist
#   ./scripts/serve.sh --force      # kill whatever is already listening on the port first
#   PORT=9000 ./scripts/serve.sh    # serve on a custom port

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
PORT="${PORT:-8000}"

SKIP_BUILD=false
SKIP_TESTS=false
FORCE=false
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=true ;;
    --skip-tests) SKIP_TESTS=true ;;
    --force) FORCE=true ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 [--skip-build] [--skip-tests] [--force]" >&2
      exit 1
      ;;
  esac
done

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

# --- Port pre-flight check ---------------------------------------------------
# Fail fast with a clear message (instead of an opaque uvicorn bind error) if
# something is already listening on the target port, since it's easy to leave
# a previous run of this script alive in another terminal/session.
existing_pid="$(lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$existing_pid" ]]; then
  if [[ "$FORCE" == true ]]; then
    log "Port $PORT is in use by PID $existing_pid - killing it (--force)"
    kill $existing_pid
    sleep 1
  else
    echo "Port $PORT is already in use by PID $existing_pid:" >&2
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
    echo >&2
    echo "Stop that process first, re-run with --force to kill it automatically, or use PORT=<n> to pick a different port." >&2
    exit 1
  fi
fi

# --- Backend virtualenv -----------------------------------------------------
if [[ ! -x "$VENV_PY" ]]; then
  log "Creating backend virtualenv"
  python3 -m venv "$BACKEND_DIR/.venv"
fi

log "Installing backend dependencies (including test/dev)"
"$VENV_PY" -m pip install -q --upgrade pip -r "$BACKEND_DIR/requirements-dev.txt"

# --- Frontend build ----------------------------------------------------------
if [[ "$SKIP_BUILD" == true ]]; then
  log "Skipping frontend build (--skip-build)"
else
  log "Installing frontend dependencies"
  # --no-audit: the install itself is instant, but npm's audit is a separate
  # POST to registry.npmjs.org that some networks (a sandboxing proxy, a
  # corporate firewall) black-hole rather than refuse, and npm then retries
  # it for minutes with nothing on screen but a spinner. CI runs `npm ci`,
  # which audits on its own.
  (cd "$FRONTEND_DIR" && npm install --no-fund --no-audit)

  log "Building frontend (tsc -b && vite build)"
  (cd "$FRONTEND_DIR" && npm run build)
fi

# --- Backend tests -----------------------------------------------------------
if [[ "$SKIP_TESTS" == true ]]; then
  log "Skipping backend tests (--skip-tests)"
else
  log "Running backend tests"
  (cd "$BACKEND_DIR" && .venv/bin/pytest -q)
fi

# --- Start the server --------------------------------------------------------
log "Starting server on http://localhost:$PORT (serving frontend/dist + API/Socket.IO)"
cd "$BACKEND_DIR"
exec .venv/bin/python -m app.server
