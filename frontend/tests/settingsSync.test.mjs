import assert from "node:assert/strict";
import test from "node:test";

import { createSettingsSync } from "../src/lib/settingsSync.ts";

/** A sync whose clock is a queue the test drains by hand. */
function harness({ canSync = () => true, fail = false } = {}) {
  const sent = [];
  const timers = [];
  const sync = createSettingsSync({
    send: async (batch) => {
      sent.push(batch);
      if (fail) throw new Error("refused");
    },
    canSync,
    delayMs: 400,
    setTimer: (callback) => {
      timers.push(callback);
      return timers.length;
    },
    clearTimer: (handle) => {
      timers[handle - 1] = null;
    },
  });
  const tick = async () => {
    const due = timers.filter(Boolean);
    timers.length = 0;
    for (const callback of due) callback();
    await new Promise((resolve) => setImmediate(resolve));
  };
  return { sync, sent, tick };
}

test("changes made together are sent as one request", async () => {
  const { sync, sent, tick } = harness();
  sync.queue({ volume: 0.1 });
  sync.queue({ volume: 0.2 });
  sync.queue({ soundEffects: false });
  assert.deepEqual(sent, [], "nothing goes out until the quiet period ends");
  await tick();
  assert.deepEqual(sent, [{ volume: 0.2, soundEffects: false }]);
});

test("closing the pane flushes what is still waiting", async () => {
  const { sync, sent } = harness();
  sync.queue({ theme: "dark" });
  await sync.flush();
  assert.deepEqual(sent, [{ theme: "dark" }]);
  await sync.flush();
  assert.equal(sent.length, 1, "an empty flush sends nothing");
});

test("a guest's changes never reach the network", async () => {
  const { sync, sent } = harness({ canSync: () => false });
  sync.queue({ theme: "dark" });
  await sync.flush();
  assert.deepEqual(sent, []);
  assert.deepEqual(sync.pendingKeys(), [], "and nothing is left waiting for a login");
});

test("a refused write is reported once, and the next change still goes out", async () => {
  const { sync, sent, tick } = harness({ fail: true });
  const reports = [];
  sync.onError((message) => reports.push(message));
  sync.queue({ theme: "dark" });
  await tick();
  assert.equal(reports.length, 1);
  assert.match(reports[0], /applies here/);
  sync.queue({ theme: "light" });
  await tick();
  assert.equal(sent.length, 2, "a failure does not stall the queue");
});

test("a change made while a request is in the air waits for it and follows", async () => {
  let release;
  const sent = [];
  const sync = createSettingsSync({
    send: (batch) =>
      new Promise((resolve) => {
        sent.push(batch);
        release = resolve;
      }),
    canSync: () => true,
    delayMs: 0,
    setTimer: (callback) => {
      callback();
      return 1;
    },
    clearTimer: () => {},
  });
  sync.queue({ volume: 0.5 });
  const first = sync.flush();
  sync.queue({ volume: 0.9 });
  assert.equal(sent.length, 1, "the second change waits rather than overtaking");
  release();
  await first;
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(sent[1], { volume: 0.9 });
});
