#!/usr/bin/env bash
# Build and run the browser canvas benchmark against an isolated local server.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PORT="${PORT:-8765}"
BASE_URL="http://127.0.0.1:$PORT"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

if lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  log "Port $PORT is already in use; choose another with PORT=<number>"
  exit 1
fi

log "Building frontend"
(cd "$FRONTEND_DIR" && npm run build --silent)

log "Starting benchmark server on $BASE_URL"
(cd "$BACKEND_DIR" && .venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port "$PORT" --log-level warning) &
SERVER_PID=$!

cleanup() {
  log "Stopping benchmark server (PID: $SERVER_PID)"
  kill "$SERVER_PID" 2>/dev/null || true
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

log "Running real-time canvas browser profiles"
"$BACKEND_DIR/.venv/bin/python" "$ROOT_DIR/benchmarks/canvas.py" \
  --base-url "$BASE_URL" "$@"
