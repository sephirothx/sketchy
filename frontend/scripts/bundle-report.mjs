#!/usr/bin/env node
/* What a first visit downloads, measured the way a browser receives it.

Reads a production build (default `dist/`), finds the entry script and
stylesheet `index.html` names plus every chunk they import statically, and
prints raw, gzip -9 and brotli sizes - for that first-load set and for every
other chunk, which is only fetched when something asks for it.

    npm run build && node scripts/bundle-report.mjs [dist] [--json]
    node scripts/bundle-report.mjs dist --budget js=215,css=41

Every reader also downloads one language chunk before the first paint - their
own, which the page shell asks for (#1426) - so the first-load figure counts
the largest of them with its imports, read from the plan `index.html` carries.
English used to be in the entry and counted; the other seven were not, and
real first loads were about 240 KB against a 215 KB budget.

`--budget` fails the run when the first-load set's gzip size, in KB, is over
either figure: `npm run bundle:check` is what CI runs after the build, so a
page that slips back into the entry chunk is caught by the change that did it
rather than noticed at launch (#475).

Written for the frontend performance epic (#981), so each change in it is
measured the same way before and after. */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";

const args = process.argv.slice(2);
const json = args.includes("--json");
const budgetArg = args[args.indexOf("--budget") + 1];
const budget = args.includes("--budget")
  ? Object.fromEntries(budgetArg.split(",").map((pair) => pair.split("=")).map(([k, v]) => [k, Number(v)]))
  : null;
const dist = args.find((arg, i) => !arg.startsWith("--") && args[i - 1] !== "--budget") ?? "dist";
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

// The page shell's plan of what each reader's language needs (#1426).
const plan = html.match(/var p=(\{"locales":.*?\});/);
const languages = plan ? JSON.parse(plan[1]).locales : {};
const byFile = new Map(rows.map((row) => [row.file, row]));
const language = Object.entries(languages)
  .map(([locale, files]) => ({
    locale,
    rows: files.map((path) => byFile.get(path.replace(/^assets\//, ""))).filter((row) => row && !row.first),
  }))
  .map((entry) => ({ ...entry, size: total(entry.rows) }))
  .sort((a, b) => b.size.gzip - a.size.gzip)[0];
for (const row of language?.rows ?? []) row.language = true;

const first = rows.filter((row) => row.first);
const firstJs = total([...first.filter((r) => r.file.endsWith(".js")), ...(language?.rows ?? [])]);
const report = {
  firstLoad: { js: firstJs, css: total(first.filter((r) => r.file.endsWith(".css"))), all: total([...first, ...(language?.rows ?? [])]) },
  largestLanguage: language ? { locale: language.locale, ...language.size } : null,
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
  if (report.largestLanguage) {
    console.log(`  (js includes the largest language, ${report.largestLanguage.locale}: ${kb(report.largestLanguage.gzip).trim()} KB gzip)`);
  }
  console.log("\nchunks (* = first load, + = the largest language)");
  for (const row of report.chunks) {
    console.log(`${row.first ? "*" : row.language ? "+" : " "} ${kb(row.raw)}  ${kb(row.gzip)}  ${kb(row.brotli)}  ${row.file}`);
  }
}

if (budget) {
  const over = Object.entries(budget).filter(([kind, limit]) => report.firstLoad[kind].gzip / 1000 > limit);
  for (const [kind, limit] of over) {
    console.error(`\nfirst-load ${kind} is ${(report.firstLoad[kind].gzip / 1000).toFixed(1)} KB gzip, over its ${limit} KB budget`);
  }
  if (over.length) process.exit(1);
  console.log(`\nwithin budget: ${Object.entries(budget).map(([k, v]) => `${k} <= ${v} KB gzip`).join(", ")}`);
}
