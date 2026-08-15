#!/usr/bin/env bash
# Run near-limit decode/replay measurements in a real browser.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
PORT="${PORT:-4174}"
BASE_URL="http://127.0.0.1:$PORT"

if lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  printf 'Port %s is already in use; choose another with PORT=<number>\n' "$PORT"
  exit 1
fi

(cd "$FRONTEND_DIR" && npm run dev --silent -- --host 127.0.0.1 --port "$PORT") &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

for _ in {1..40}; do
  if curl -fsS "$BASE_URL/benchmarks/canvas-history.html" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! curl -fsS "$BASE_URL/benchmarks/canvas-history.html" >/dev/null; then
  printf 'Vite benchmark server did not become ready\n'
  exit 1
fi

"$ROOT_DIR/backend/.venv/bin/python" \
  "$ROOT_DIR/benchmarks/canvas_history_browser.py" \
  --base-url "$BASE_URL" "$@"
