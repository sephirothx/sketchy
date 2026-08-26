#!/usr/bin/env bash
# Rasterises the brand PNGs from the SVG sources written by derive-assets.mjs.
#
# PNGs are committed: they change about as often as the product name, so a
# permanent build step would cost more than it saves. Regenerate with:
#   node scripts/brand/derive-assets.mjs && bash scripts/brand/render-rasters.sh
#
# Needs network on the first run (npx fetches sharp-cli).
#
# sharp-cli's -o is a directory, not a filename, and it keeps the input's
# basename — so each source is staged under its output name first.
set -euo pipefail
cd "$(dirname "$0")/../.."

SRC=scripts/brand/raster
OUT=frontend/public
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

render() {  # render <source> <out-basename> <w> <h>
  cp "$SRC/$1" "$TMP/$2.svg"
  npx --yes sharp-cli@5 -i "$TMP/$2.svg" -o "$OUT" resize "$3" "$4" --format png >/dev/null
  echo "  $OUT/$2.png  ${3}x${4}"
}

render icon-square.svg   apple-touch-icon   180  180
render icon-square.svg   icon-192           192  192
render icon-square.svg   icon-512           512  512
render icon-maskable.svg icon-maskable-512  512  512
render og-image.svg      og-image          1200  630
