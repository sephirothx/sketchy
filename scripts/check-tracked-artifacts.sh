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

# "SQLite format 3\0", the 16-byte header every SQLite database opens with.
SQLITE_MAGIC_HEX="53514c69746520666f726d6174203300"

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

# Checking is keyed on content, so one path can legitimately be checked several
# times - the tracked tree and each version in the range. Reporting is keyed on
# the path, so a single offending file is one line and counts once.
reported=""
report() {
  case "$reported" in
    *"|$1|"*) return 0 ;;
  esac
  reported="$reported|$1|"
  printf '  %s\n      %s\n' "$1" "$2" >&2
  violations=$((violations + 1))
}

# The head of a file, captured once and sniffed twice. It goes to a temporary
# file rather than a variable because the SQLite magic ends in a NUL, and command
# substitution strips those - the magic cannot survive the round trip.
#
# 128 bytes is enough for both sniffs: 16 for the SQLite header, and one PEM
# armour line, which is at most `-----BEGIN PGP PRIVATE KEY BLOCK-----`.
HEAD_BYTES="$(mktemp "${TMPDIR:-/tmp}/check-tracked-artifacts.XXXXXX")"
trap 'rm -f "$HEAD_BYTES"' EXIT

# `git cat-file` is killed by SIGPIPE once head has taken its bytes, which
# pipefail would otherwise turn into a fatal error, so its failure is swallowed
# deliberately.
capture_head_of_blob() {
  { git cat-file blob "$1" 2>/dev/null || true; } | head -c 128 > "$HEAD_BYTES"
}

capture_head_of_file() {
  head -c 128 -- "$1" > "$HEAD_BYTES"
}

looks_like_sqlite() {
  [ "$(od -An -v -tx1 -N16 "$HEAD_BYTES" | tr -d ' \n')" = "$SQLITE_MAGIC_HEX" ]
}

# PEM armour is plain text on the first line, so a shell glob is enough and there
# is no NUL to lose. Covers `PRIVATE KEY`, `RSA/EC/DSA/OPENSSH PRIVATE KEY`,
# `ENCRYPTED PRIVATE KEY`, and `PGP PRIVATE KEY BLOCK`.
#
# There is deliberately no equivalent for .p12/.pfx: PKCS#12 is DER, and its
# opening bytes are a generic ASN.1 SEQUENCE that any number of innocent binary
# formats share. Those stay caught by name only.
looks_like_pem_private_key() {
  local first
  IFS= read -r first < "$HEAD_BYTES" || true
  first=${first%$'\r'}
  case "$first" in
    "-----BEGIN "*"PRIVATE KEY-----"|"-----BEGIN "*"PRIVATE KEY BLOCK-----") return 0 ;;
  esac
  return 1
}

check_entry() {
  local path=$1
  local blob=${2:-}
  local reason
  local key

  # Keyed on the content as well as the path, because `git rev-list` walks
  # newest first: a path that held a database and was later overwritten with
  # something harmless would otherwise be marked seen at its benign version and
  # never checked at the version that matters. Same reason the tracked-tree scan
  # cannot shadow the range scan at a shared path.
  key="$blob:$path"
  case "$seen" in
    *"|$key|"*) return 0 ;;
  esac
  seen="$seen|$key|"

  if reason=$(deny_name "$path"); then
    report "$path" "$reason"
    return 0
  fi

  if [ -n "$blob" ]; then
    capture_head_of_blob "$blob"
  elif [ -f "$path" ]; then
    capture_head_of_file "$path"
  else
    return 0
  fi

  if looks_like_sqlite; then
    report "$path" "SQLite database, whatever the filename says"
  elif looks_like_pem_private_key; then
    report "$path" "PEM private key, whatever the filename says"
  fi
}

while IFS= read -r -d '' path; do
  check_entry "$path"
done < <(git ls-files -z)

if [ "$mode" = "range" ]; then
  # `git diff-tree -z` emits ':<mode> <mode> <sha> <sha> <status>\0<path>\0', so
  # each file costs two reads. --root makes an initial commit list its own files
  # instead of nothing.
  #
  # --diff-filter=d is every change except a deletion, not just additions: a
  # tracked placeholder overwritten with a database is a modification, and its
  # blob lands in history exactly like an addition would.
  #
  # --no-renames keeps a rename as a delete plus an add, which matters twice.
  # A detected rename would be reported as R and skipped by the filter, and it
  # would also emit a third NUL-separated field for the destination path, which
  # the two-read loop below would misparse.
  #
  # -m is what makes a merge commit produce a file list at all. Without it
  # `diff-tree` prints nothing for a merge, so anything that exists only in the
  # merge result - a conflict resolved by pasting in the wrong file - is
  # invisible. With it, each parent is diffed separately, and the blob-keyed
  # dedupe below collapses the entries that repeat across parents. -z keeps the
  # two-field-per-entry stream intact; -m adds no commit-id records to it.
  # Resolved up front rather than streamed, so a range that does not resolve is
  # an error instead of an empty walk. Streaming it hid the failure completely:
  # `git rev-list` printed `fatal:` into the void, the loop read nothing, and the
  # scan reported success - the exact fail-open shape this guard exists to close,
  # sitting in the guard.
  if ! commits="$(git rev-list "${range_args[@]}" 2>&1)"; then
    printf 'check-tracked-artifacts: cannot resolve the range %s\n' "${range_args[*]}" >&2
    printf '%s\n' "$commits" >&2
    exit 2
  fi

  while IFS= read -r commit; do
    [ -n "$commit" ] || continue
    while IFS= read -r -d '' meta && IFS= read -r -d '' path; do
      check_entry "$path" "$(printf '%s\n' "$meta" | awk '{print $4}')"
    done < <(git diff-tree -r -m -z --no-commit-id --no-renames --diff-filter=d --root "$commit")
  done <<EOF
$commits
EOF
fi

if [ "$violations" -gt 0 ]; then
  printf '\ncheck-tracked-artifacts: refusing %s file(s) above.\n' "$violations" >&2
  printf 'Remove it from the commit (git rm --cached <path>) and add a matching\n' >&2
  printf 'pattern to .gitignore. If a file is legitimate, widen the rules in\n' >&2
  printf 'scripts/check-tracked-artifacts.sh rather than skipping the check.\n' >&2
  exit 1
fi

exit 0
