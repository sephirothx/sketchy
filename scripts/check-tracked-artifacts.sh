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
#   2. The bytes are a SQLite database, whatever the file is called. That is the
#      backstop: rename the artifact to notes.txt and this still catches it.
#
# Usage:
#   check-tracked-artifacts.sh                  scan every tracked file
#   check-tracked-artifacts.sh --range <spec>   also scan every file ADDED by the
#                                               commits in <spec> (any rev-list
#                                               arguments), so a file that is added
#                                               and deleted inside one push - which
#                                               leaves the tip tree clean and the
#                                               history polluted forever - still
#                                               fails.

set -euo pipefail

# "SQLite format 3\0", the 16-byte header every SQLite database opens with.
SQLITE_MAGIC_HEX="53514c69746520666f726d6174203300"

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

mode="worktree"
range_args=()

while [ $# -gt 0 ]; do
  case "$1" in
    --range)
      shift
      if [ $# -eq 0 ]; then
        printf 'check-tracked-artifacts: --range needs at least one revision\n' >&2
        exit 2
      fi
      mode="range"
      range_args=("$@")
      break
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

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  printf 'check-tracked-artifacts: not inside a git work tree\n' >&2
  exit 2
fi

cd "$(git rev-parse --show-toplevel)"

violations=0
seen=""

# Name rules. Echoes why the path is refused and returns 0; returns 1 to allow.
deny_name() {
  local base=${1##*/}

  case "$base" in
    .env.example)
      return 1
      ;;
    .env|.env.?*)
      echo "environment file - secrets belong outside the repository"
      return 0
      ;;
  esac

  case "$base" in
    *.db|*.db.*|*.db-shm|*.db-wal|*.db-journal|*.sqlite*)
      echo "database file, sidecar, or backup copy"
      return 0
      ;;
    *.pem|*.key|*.p12|*.pfx|*.keystore|id_rsa|id_ecdsa|id_ed25519)
      echo "private key or certificate"
      return 0
      ;;
  esac

  return 1
}

report() {
  printf '  %s\n      %s\n' "$1" "$2" >&2
  violations=$((violations + 1))
}

# The first 16 bytes of a blob, as hex. `git cat-file` is killed by SIGPIPE once
# head has taken its 16 bytes, which pipefail would otherwise turn into a fatal
# error, so its failure is swallowed deliberately.
head_hex_of_blob() {
  { git cat-file blob "$1" 2>/dev/null || true; } | head -c 16 | od -An -v -tx1 | tr -d ' \n'
}

head_hex_of_file() {
  head -c 16 -- "$1" | od -An -v -tx1 | tr -d ' \n'
}

check_entry() {
  local path=$1
  local blob=${2:-}
  local reason
  local head_hex

  case "$seen" in
    *"|$path|"*) return 0 ;;
  esac
  seen="$seen|$path|"

  if reason=$(deny_name "$path"); then
    report "$path" "$reason"
    return 0
  fi

  if [ -n "$blob" ]; then
    head_hex=$(head_hex_of_blob "$blob")
  elif [ -f "$path" ]; then
    head_hex=$(head_hex_of_file "$path")
  else
    return 0
  fi

  if [ "$head_hex" = "$SQLITE_MAGIC_HEX" ]; then
    report "$path" "SQLite database, whatever the filename says"
  fi
}

while IFS= read -r -d '' path; do
  check_entry "$path"
done < <(git ls-files -z)

if [ "$mode" = "range" ]; then
  # `git diff-tree -z` emits ':<mode> <mode> <sha> <sha> <status>\0<path>\0', so
  # each file costs two reads. --root makes an initial commit list its own files
  # instead of nothing.
  while IFS= read -r commit; do
    while IFS= read -r -d '' meta && IFS= read -r -d '' path; do
      check_entry "$path" "$(printf '%s\n' "$meta" | awk '{print $4}')"
    done < <(git diff-tree -r -z --no-commit-id --diff-filter=A --root "$commit")
  done < <(git rev-list "${range_args[@]}")
fi

if [ "$violations" -gt 0 ]; then
  printf '\ncheck-tracked-artifacts: refusing %s file(s) above.\n' "$violations" >&2
  printf 'Remove it from the commit (git rm --cached <path>) and add a matching\n' >&2
  printf 'pattern to .gitignore. If a file is legitimate, widen the rules in\n' >&2
  printf 'scripts/check-tracked-artifacts.sh rather than skipping the check.\n' >&2
  exit 1
fi

exit 0
