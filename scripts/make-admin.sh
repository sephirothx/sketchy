#!/usr/bin/env bash
# Promote a registered account to administrator on this checkout's database.
#
# A thin wrapper over the guarded command in backend/app/auth/admin.py, which
# is the one way an administrator is created (R-ACCT-07): it refuses to run
# once one exists, insists on a registered account, and writes the promotion
# and its reason to the audit log. This script only saves remembering the
# module path, the venv, and a reason for a development database.
#
# Usage:
#   ./scripts/make-admin.sh <username> [reason]
#   DATABASE_URL=sqlite+aiosqlite:////path/to/other.db ./scripts/make-admin.sh Ada
#
# Without DATABASE_URL it acts on backend/sketchy.db, the database a server
# started from this checkout uses; a running server picks the role up on the
# account's next request, so nothing needs restarting.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_PY="$BACKEND_DIR/.venv/bin/python"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <username> [reason]" >&2
  exit 2
fi

USERNAME="$1"
REASON="${2:-Promoted by scripts/make-admin.sh on $(hostname -s 2>/dev/null || hostname)}"

if [[ ! -x "$VENV_PY" ]]; then
  echo "No backend virtualenv at $VENV_PY - see README → Setup → Backend." >&2
  exit 1
fi

cd "$BACKEND_DIR"
exec "$VENV_PY" -m app.auth.admin --username "$USERNAME" --reason "$REASON"
