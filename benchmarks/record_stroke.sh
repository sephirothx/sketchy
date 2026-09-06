#!/usr/bin/env bash
# Record real drawing traffic through the production client into a fixture.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/benchmarks/with_server.sh" "$ROOT_DIR/benchmarks/record_stroke.py" "$@"
