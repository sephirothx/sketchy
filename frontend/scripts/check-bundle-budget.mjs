import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const distRoot = join(frontendRoot, "dist");
const manifest = JSON.parse(
  readFileSync(join(distRoot, ".vite", "manifest.json"), "utf8"),
);
const budget = JSON.parse(
  readFileSync(join(frontendRoot, "bundle-budget.json"), "utf8"),
);

function fail(message) {
  console.error(`Bundle budget failed: ${message}`);
  process.exitCode = 1;
}

function assetClosure(entryKey) {
  const manifestEntries = new Set();
  const assets = new Set();

  function visit(key) {
    if (manifestEntries.has(key)) return;
    manifestEntries.add(key);
    const entry = manifest[key];
    if (!entry) {
      fail(`manifest entry ${key} is missing`);
      return;
    }
    if (entry.file) assets.add(entry.file);
    for (const css of entry.css ?? []) assets.add(css);
    for (const importedKey of entry.imports ?? []) visit(importedKey);
  }

  visit(entryKey);
  return assets;
}

function sizes(assets) {
  let rawBytes = 0;
  let gzipBytes = 0;
  for (const asset of assets) {
    const contents = readFileSync(join(distRoot, asset));
    rawBytes += contents.byteLength;
    gzipBytes += gzipSync(contents, { level: 9 }).byteLength;
  }
  return { rawBytes, gzipBytes };
}

const entryKey = "index.html";
const entry = manifest[entryKey];
if (!entry?.isEntry) fail(`${entryKey} is not marked as the build entry`);

const initialAssets = assetClosure(entryKey);
const initialSizes = sizes(initialAssets);

if (initialSizes.rawBytes > budget.initialLobby.maxRawBytes) {
  fail(
    `initial raw bytes ${initialSizes.rawBytes} exceed ${budget.initialLobby.maxRawBytes}`,
  );
}
if (initialSizes.gzipBytes > budget.initialLobby.maxGzipBytes) {
  fail(
    `initial gzip bytes ${initialSizes.gzipBytes} exceed ${budget.initialLobby.maxGzipBytes}`,
  );
}

for (const routeKey of budget.dynamicRoutes) {
  const route = manifest[routeKey];
  if (!route?.isDynamicEntry) {
    fail(`${routeKey} is not emitted as a dynamic entry`);
    continue;
  }
  if (!(entry.dynamicImports ?? []).includes(routeKey)) {
    fail(`${routeKey} is not a dynamic import of the application entry`);
  }
  if (initialAssets.has(route.file)) {
    fail(`${route.file} leaked into the initial lobby assets`);
  }

  const lazyAssets = [...assetClosure(routeKey)].filter(
    (asset) => !initialAssets.has(asset),
  );
  console.log(`${routeKey}: ${lazyAssets.join(", ")}`);
}

const rawReduction =
  1 - initialSizes.rawBytes / budget.baseline.initialRawBytes;
const gzipReduction =
  1 - initialSizes.gzipBytes / budget.baseline.initialGzipBytes;

console.log(`Initial lobby assets: ${[...initialAssets].join(", ")}`);
console.log(
  `Initial lobby: ${initialSizes.rawBytes} raw bytes, ${initialSizes.gzipBytes} gzip bytes`,
);
console.log(
  `Baseline reduction: ${(rawReduction * 100).toFixed(1)}% raw, ${(gzipReduction * 100).toFixed(1)}% gzip`,
);

if (process.exitCode) process.exit(process.exitCode);
