#!/usr/bin/env node
/* What a first visit downloads, measured the way a browser receives it.

Reads a production build (default `dist/`), finds the entry script and
stylesheet `index.html` names plus every chunk they import statically, and
prints raw, gzip -9 and brotli sizes - for that first-load set and for every
other chunk, which is only fetched when something asks for it.

    npm run build && node scripts/bundle-report.mjs [dist] [--json]

Written for the frontend performance epic (#981), so each change in it is
measured the same way before and after. */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";

const args = process.argv.slice(2);
const json = args.includes("--json");
const dist = args.find((arg) => !arg.startsWith("--")) ?? "dist";
const assets = join(dist, "assets");

function sizes(file) {
  const bytes = readFileSync(join(assets, file));
  return {
    raw: bytes.length,
    gzip: gzipSync(bytes, { level: 9 }).length,
    brotli: brotliCompressSync(bytes, {
      params: { [constants.BROTLI_PARAM_QUALITY]: 11 },
    }).length,
  };
}

// Static imports only: `import("...")` is what a chunk fetches on demand.
function staticImports(file) {
  const code = readFileSync(join(assets, file), "utf8");
  const found = new Set();
  const pattern = /(?:^|[;\n}])\s*import\s*(?:[\w$*{},\s]+from\s*)?["']\.\/([\w.-]+\.js)["']/g;
  for (const match of code.matchAll(pattern)) found.add(match[1]);
  return [...found];
}

const html = readFileSync(join(dist, "index.html"), "utf8");
const named = [...html.matchAll(/(?:src|href)="\/assets\/([\w.-]+\.(?:js|css))"/g)].map((m) => m[1]);
const firstLoad = new Set();
const queue = [...named];
while (queue.length) {
  const file = queue.shift();
  if (firstLoad.has(file)) continue;
  firstLoad.add(file);
  if (file.endsWith(".js")) queue.push(...staticImports(file));
}

const all = readdirSync(assets).filter((file) => /\.(js|css)$/.test(file));
const rows = all.map((file) => ({ file, first: firstLoad.has(file), ...sizes(file) }));
const total = (list) =>
  list.reduce((sum, row) => ({
    raw: sum.raw + row.raw,
    gzip: sum.gzip + row.gzip,
    brotli: sum.brotli + row.brotli,
  }), { raw: 0, gzip: 0, brotli: 0 });

const first = rows.filter((row) => row.first);
const report = {
  firstLoad: { js: total(first.filter((r) => r.file.endsWith(".js"))), css: total(first.filter((r) => r.file.endsWith(".css"))), all: total(first) },
  chunks: rows.sort((a, b) => b.raw - a.raw),
};

if (json) {
  console.log(JSON.stringify(report, null, 2));
} else {
  const kb = (n) => (n / 1000).toFixed(1).padStart(8);
  console.log("first load        raw KB   gzip KB  brotli KB");
  for (const [label, t] of Object.entries(report.firstLoad)) {
    console.log(`  ${label.padEnd(12)}${kb(t.raw)}  ${kb(t.gzip)}  ${kb(t.brotli)}`);
  }
  console.log("\nchunks (* = first load)");
  for (const row of report.chunks) {
    console.log(`${row.first ? "*" : " "} ${kb(row.raw)}  ${kb(row.gzip)}  ${kb(row.brotli)}  ${row.file}`);
  }
}
