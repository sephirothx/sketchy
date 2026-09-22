import assert from "node:assert/strict";
import test from "node:test";

import { reloadForMissingChunk } from "../src/lib/chunkReload.ts";

function environment({ answers = true, stored = null, throws = false } = {}) {
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
    serverAnswers: async () => answers,
    reload: () => {
      calls.reloads += 1;
    },
  };
}

test("a missing chunk on a server that answers reloads, and remembers it did", async () => {
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

test("an unreachable server is not answered with a reload", async () => {
  // A reload there lands on the browser's error page instead of the app's.
  const env = environment({ answers: false });
  assert.equal(await reloadForMissingChunk(env), false);
  assert.equal(env.calls.reloads, 0);
  assert.equal(env.calls.written, null, "nothing is spent on a reload that did not happen");
});

test("without storage there is no reload, since a loop could not be stopped", async () => {
  const env = environment({ throws: true });
  assert.equal(await reloadForMissingChunk(env), false);
  assert.equal(env.calls.reloads, 0);
});
