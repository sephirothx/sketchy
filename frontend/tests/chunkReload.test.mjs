import assert from "node:assert/strict";
import test from "node:test";

import { failedChunkUrl, reloadForMissingChunk } from "../src/lib/chunkReload.ts";

function environment({ gone = true, stored = null, throws = false } = {}) {
  const calls = { reloads: 0, written: null };
  return {
    calls,
    build: "abc123 2026-09-22 12:00:00",
    storage: {
      getItem: () => {
        if (throws) throw new Error("storage refused");
        return stored;
      },
      setItem: (_key, value) => {
        calls.written = value;
      },
    },
    chunkIsGone: async () => gone,
    reload: () => {
      calls.reloads += 1;
    },
  };
}

test("a chunk the server says is gone reloads, and remembers it did", async () => {
  const env = environment();
  assert.equal(await reloadForMissingChunk(env), true);
  assert.equal(env.calls.reloads, 1);
  assert.equal(env.calls.written, env.build);
});

test("the same build does not reload twice", async () => {
  const env = environment({ stored: "abc123 2026-09-22 12:00:00" });
  assert.equal(await reloadForMissingChunk(env), false);
  assert.equal(env.calls.reloads, 0);
});

test("a newer build may reload once more", async () => {
  const env = environment({ stored: "old000 2026-09-01 09:00:00" });
  assert.equal(await reloadForMissingChunk(env), true);
});

test("a chunk that is still there, or a server that cannot say, is not answered with a reload", async () => {
  // Unreachable: a reload lands on the browser's error page. A one-off
  // failure: a reload throws the page away for nothing.
  const env = environment({ gone: false });
  assert.equal(await reloadForMissingChunk(env), false);
  assert.equal(env.calls.reloads, 0);
  assert.equal(env.calls.written, null, "nothing is spent on a reload that did not happen");
});

test("without storage there is no reload, since a loop could not be stopped", async () => {
  const env = environment({ throws: true });
  assert.equal(await reloadForMissingChunk(env), false);
  assert.equal(env.calls.reloads, 0);
});

test("the failed chunk is read from the browser's error, where it is named", () => {
  assert.equal(
    failedChunkUrl(new TypeError("Failed to fetch dynamically imported module: https://sketchy.example/assets/RulesPage-Ab12.js")),
    "https://sketchy.example/assets/RulesPage-Ab12.js",
  );
  assert.equal(
    failedChunkUrl(new TypeError("error loading dynamically imported module: http://localhost:8000/assets/de-X9.js")),
    "http://localhost:8000/assets/de-X9.js",
  );
  // Safari's message names nothing; the caller falls back to asking the server.
  assert.equal(failedChunkUrl(new TypeError("Importing a module script failed.")), null);
});
