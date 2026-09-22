// Write a Brotli and a gzip copy beside every compressible file in dist/ (#978).
//
// The server gzipped the bundle at level 9 on its event loop for every client
// that asked - ~22 ms of loop time per cold page load, in chunks up to 12 ms,
// on the loop every room's strokes share - and a deploy is exactly when every
// client asks at once. Compressed here, once, the server hands over the file
// the browser accepts (`app/main.py`, `SPAStaticFiles`) and compresses nothing.
// Brotli at its highest quality is affordable at build time and not at request
// time. A copy that saves nothing is not written, so its absence means "serve
// the original".
import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import { join, extname } from "node:path";
import { brotliCompressSync, gzipSync, constants } from "node:zlib";
import { fileURLToPath } from "node:url";

const DIST = fileURLToPath(new URL("../dist/", import.meta.url));
const COMPRESSIBLE = new Set([".js", ".mjs", ".css", ".html", ".svg", ".json", ".webmanifest", ".txt", ".xml", ".map"]);
const MIN_BYTES = 1024;

async function* files(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) yield* files(path);
    else yield path;
  }
}

let written = 0;
let before = 0;
let after = 0;
for await (const path of files(DIST)) {
  if (!COMPRESSIBLE.has(extname(path)) || (await stat(path)).size < MIN_BYTES) continue;
  const original = await readFile(path);
  const brotli = brotliCompressSync(original, {
    params: {
      [constants.BROTLI_PARAM_QUALITY]: constants.BROTLI_MAX_QUALITY,
      [constants.BROTLI_PARAM_SIZE_HINT]: original.length,
    },
  });
  const gzip = gzipSync(original, { level: 9 });
  for (const [suffix, bytes] of [[".br", brotli], [".gz", gzip]]) {
    if (bytes.length < original.length) {
      await writeFile(path + suffix, bytes);
      written += 1;
    }
  }
  before += original.length;
  after += brotli.length;
}
console.log(`precompress: ${written} files, ${(before / 1024).toFixed(0)} KB -> ${(after / 1024).toFixed(0)} KB brotli`);
