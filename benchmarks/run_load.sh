#!/usr/bin/env bash
# The release load gate against a throwaway server (#461).
#
# Starts a server with the limits a swarm from one address would otherwise trip
# (guest provisioning, name lookups, the socket ceiling) and a metrics token,
# then runs benchmarks/load.py against it. Every argument is passed through.
#
# Usage: benchmarks/run_load.sh [load.py args...]
#   PORT=8765     the throwaway server's port
#   SKIP_BUILD=1  reuse frontend/dist as it is
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export METRICS_TOKEN="${METRICS_TOKEN:-load-gate-token}"
export GUEST_PROVISION_LIMIT="${GUEST_PROVISION_LIMIT:-100000}"
export GUEST_PROVISION_DAILY_LIMIT="${GUEST_PROVISION_DAILY_LIMIT:-100000}"
export AUTH_LOOKUP_LIMIT="${AUTH_LOOKUP_LIMIT:-100000}"
export AUTH_LOGIN_LIMIT="${AUTH_LOGIN_LIMIT:-100000}"
export SOCKET_LIMIT="${SOCKET_LIMIT:-2000}"
export ROOM_GLOBAL_LIMIT="${ROOM_GLOBAL_LIMIT:-400}"
export ROOM_CREATE_LIMIT="${ROOM_CREATE_LIMIT:-1000}"
export LOG_LEVEL="${LOG_LEVEL:-warning}"
exec "$ROOT/benchmarks/with_server.sh" "$ROOT/benchmarks/load.py" "$@"
