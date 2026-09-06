#!/usr/bin/env bash
# Build the frontend, start an isolated local server, run one benchmark
# script against it, and stop the server. Shared by the browser-driven
# benchmarks so each one is only the measurement it makes.
#
# Usage: benchmarks/with_server.sh <script.py> [script args...]
#   PORT=8765        port the throwaway server listens on
#   SKIP_BUILD=1     reuse frontend/dist as it is
#   DATABASE_URL     defaults to a fresh SQLite file that is deleted afterwards,
#                    so a run never depends on, or pollutes, the dev database

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PORT="${PORT:-8765}"
BASE_URL="http://127.0.0.1:$PORT"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

if [ $# -lt 1 ]; then
  echo "usage: $0 <script.py> [args...]" >&2
  exit 2
fi
SCRIPT="$1"
shift

if lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  log "Port $PORT is already in use; choose another with PORT=<number>"
  exit 1
fi

if [ "${SKIP_BUILD:-0}" != "1" ]; then
  log "Building frontend"
  (cd "$FRONTEND_DIR" && npm run build --silent)
fi

SCRATCH_DB=""
if [ -z "${DATABASE_URL:-}" ]; then
  SCRATCH_DB="$(mktemp -t sketchy-benchmark).db"
  export DATABASE_URL="sqlite+aiosqlite:///$SCRATCH_DB"
fi

log "Starting benchmark server on $BASE_URL"
(cd "$BACKEND_DIR" && exec .venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port "$PORT" --log-level warning) &
SERVER_PID=$!

cleanup() {
  log "Stopping benchmark server (PID: $SERVER_PID)"
  kill "$SERVER_PID" 2>/dev/null || true
  if [ -n "$SCRATCH_DB" ]; then rm -f "$SCRATCH_DB" "$SCRATCH_DB-wal" "$SCRATCH_DB-shm"; fi
}
trap cleanup EXIT

for _ in {1..30}; do
  if curl -fsS "$BASE_URL/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! curl -fsS "$BASE_URL/api/health" >/dev/null; then
  log "Benchmark server did not become ready"
  exit 1
fi

log "Running $(basename "$SCRIPT")"
"$BACKEND_DIR/.venv/bin/python" "$SCRIPT" --base-url "$BASE_URL" "$@"
