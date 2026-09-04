#!/usr/bin/env bash
# Refuse to let the avatar doodle sprite drift from the generator that writes it.
#
# `frontend/public/avatars/doodles.svg` is output:
# `scripts/brand/build-avatar-doodles.mjs` inks it from the centrelines in
# `scripts/brand/avatar-doodles.mjs`. The sprite opens like source and every
# symbol in it is legible SVG, so nudging one by hand looks like it works -
# and then the next person to run the generator silently loses the nudge. This
# is the same trap `check-mockups-regenerated.sh` exists for, which has already
# cost this repository one change (#540).
#
# The generator is seeded on each doodle's id, so a rerun with unchanged
# sources rewrites byte-for-byte. That is what makes this check possible at
# all: without it, "the file moved" would mean nothing.
#
# The fix is never to revert the regeneration - it is to say the thing in
# scripts/brand/avatar-doodles.mjs and commit what the generator writes.
#
# Usage:
#   check-doodles-regenerated.sh        regenerate and report whether it moved

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sprite="$root/frontend/public/avatars/doodles.svg"

if [ ! -f "$sprite" ]; then
  echo "check-doodles-regenerated: $sprite is missing." >&2
  exit 1
fi

before="$(shasum -a 256 < "$sprite")"
node "$root/scripts/brand/build-avatar-doodles.mjs" >/dev/null
after="$(shasum -a 256 < "$sprite")"

if [ "$before" != "$after" ]; then
  {
    echo "Running scripts/brand/build-avatar-doodles.mjs rewrote"
    echo "frontend/public/avatars/doodles.svg, so it had drifted:"
    echo
    echo "  before  $before"
    echo "  after   $after"
    echo
    echo "The sprite was edited by hand, or the drawing in"
    echo "scripts/brand/avatar-doodles.mjs changed without the sprite being"
    echo "rebuilt. Put the intent in the drawing, run"
    echo "'node scripts/brand/build-avatar-doodles.mjs', and commit its output."
  } >&2
  exit 1
fi

echo "The doodle sprite matches scripts/brand/build-avatar-doodles.mjs."
