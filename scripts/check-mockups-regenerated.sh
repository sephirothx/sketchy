#!/usr/bin/env bash
# Refuse to let the tracked mockup artboards drift from the generator that
# writes them.
#
# `docs/ui-mockups/*.dc.html` and `canvas.json` are output: `tools/build.mjs`
# rewrites all of them from `tools/screens.mjs` and the `tools/pages-*.mjs`
# sources. Editing an artboard by hand looks like it works, because the file is
# what the design canvas opens - and then the next person to run the build
# silently loses the edit.
#
# That already happened. #540 added the overview's signal panels straight into
# `AdminOps.dc.html` without touching the generator, and the section survived
# only because nobody regenerated in the four months that followed.
#
# So: regenerate, and fail if any generated file moved. The fix is never to
# revert the regeneration - it is to make the generator say what the artboard
# was meant to say, then commit its output.
#
# This compares the files against themselves across the build rather than
# against HEAD, so it answers "is the build a no-op?" and not "is the tree
# committed?" - it stays usable with mockup work in progress.
#
# Usage:
#   check-mockups-regenerated.sh        regenerate and report what moved

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mockups="$root/docs/ui-mockups"

before="$(mktemp)"
after="$(mktemp)"
trap 'rm -f "$before" "$after"' EXIT

fingerprint() {
  find "$mockups" -maxdepth 1 \( -name '*.dc.html' -o -name 'canvas.json' \) -print0 \
    | sort -z | xargs -0 shasum -a 256
}

fingerprint > "$before"
node "$mockups/tools/build.mjs" >/dev/null
fingerprint > "$after"

if ! diff -q "$before" "$after" >/dev/null; then
  {
    echo "Running tools/build.mjs rewrote tracked mockups, so they had drifted:"
    echo
    diff "$before" "$after" | sed -n 's|.*/docs/ui-mockups/|  |p' | sort -u
    echo
    echo "An artboard was edited by hand, or a generator source changed without"
    echo "the artboards being rebuilt. Put the intent in docs/ui-mockups/tools/,"
    echo "run 'node tools/build.mjs' from docs/ui-mockups, and commit the output."
  } >&2
  exit 1
fi

echo "Mockup artboards match tools/build.mjs."
