#!/usr/bin/env bash
# Refuse to let a database, an environment file, or a private key become part of
# the repository.
#
# This has happened twice. First a SQLite write-ahead log: `*.db` does not match
# `sketchy.db-wal`, the file changed on every run, and anything using `git add -A`
# swept it into a commit. Then `backend/sketchy.db.broken-20260827-033005`, a whole
# 344KB database carrying a signing secret and a user row, pushed to a public
# repository - `*.db` does not match that name either, because the timestamp comes
# after the extension.
#
# Both slipped through because .gitignore only ever matched the shapes someone had
# already thought of. So this checks two independent things, and either one is
# enough to fail:
#
#   1. The name looks like an artifact, including the suffixed-backup forms that
#      got through before.
#   2. The bytes say what the file is, whatever it is called - a SQLite header,
#      or PEM private-key armour. That is the backstop: rename the artifact to
#      notes.txt and this still catches it.
#
# Usage:
#   check-tracked-artifacts.sh                  scan every tracked file
#   check-tracked-artifacts.sh --baseline       print the commit this history is
#                                               scannable from, for callers that
#                                               need a floor and have no base
#   check-tracked-artifacts.sh --floor <rev>    print <rev>, or the baseline if
#                                               <rev> is older than it, so a
#                                               caller's range can never reach
#                                               back over the baseline commit
#   check-tracked-artifacts.sh --range <spec>   also scan every file the commits in
#                                               <spec> ADD OR MODIFY (any rev-list
#                                               arguments), so a file that is added
#                                               and deleted inside one push - which
#                                               leaves the tip tree clean and the
#                                               history polluted forever - still
#                                               fails.

set -euo pipefail

# The commit that added `backend/sketchy.db.broken-20260827-033005`. Removing
# that file was a deletion and not a rewrite, so the blob is in this history for
# good, and any range reaching back to it fails forever. Callers with no base
# commit to work from use this as their floor - half-open, so the commit itself
# is excluded and everything the guard can still act on is included.
#
# It lives here so the hook and CI cannot drift apart on it. If this history is
# ever rewritten, this is the one line to change.
HISTORY_BASELINE="f0696b46e0c3305624349c8df9c55fc6595e1d44"

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

range_args=()

while [ $# -gt 0 ]; do
  case "$1" in
    --range)
      shift
      if [ $# -eq 0 ]; then
        printf 'check-tracked-artifacts: --range needs at least one revision\n' >&2
        exit 2
      fi
      range_args=("$@")
      break
      ;;
    --baseline)
      printf '%s\n' "$HISTORY_BASELINE"
      exit 0
      ;;
    --floor)
      shift
      # A fork point is wherever the branch diverged, which can be older than the
      # baseline whenever the base branch is old - and a range reaching back over
      # the baseline commit includes the database it added, so it fails forever.
      # Clamping belongs here rather than in each caller: the constant and the
      # rule that protects it stay in one place.
      if [ $# -eq 0 ]; then
        printf 'check-tracked-artifacts: --floor needs a revision\n' >&2
        exit 2
      fi
      if git rev-parse --verify --quiet "$1^{commit}" >/dev/null 2>&1 &&
        git merge-base --is-ancestor "$HISTORY_BASELINE" "$1" 2>/dev/null; then
        printf '%s\n' "$1"
      else
        printf '%s\n' "$HISTORY_BASELINE"
      fi
      exit 0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'check-tracked-artifacts: unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

# The scanner needs only Python's standard library. Batch Git reads avoid a
# subprocess for each file and historical version; the Git-only floor stays
# here so CI and the hook still resolve it without a Python environment.
# Bash 3.2 treats an empty array as unset under nounset.
if [ ${#range_args[@]} -eq 0 ]; then
  exec python3 "$(dirname "${BASH_SOURCE[0]}")/check_tracked_artifacts.py"
fi
exec python3 "$(dirname "${BASH_SOURCE[0]}")/check_tracked_artifacts.py" "${range_args[@]}"
