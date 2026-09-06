#!/usr/bin/env bash
# Build and run the browser canvas benchmark against an isolated local server.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/benchmarks/with_server.sh" "$ROOT_DIR/benchmarks/canvas.py" "$@"
