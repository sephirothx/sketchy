import assert from "node:assert/strict";
import test from "node:test";

import { createProtocolRenderer } from "../src/lib/protocolRenderer.ts";
import { createHiddenWatch, LOBBY_HIDDEN_GRACE_MS } from "../src/lib/lobbyChannel.ts";
import { MAX_GAP_MS, shouldResyncOnReturn } from "../src/lib/heartbeatSchedule.ts";

// What a tab going away and coming back costs (#886): a listener per mount,
// a subscription nobody is watching, a resync per alt-tab, and a backoff
// waited out after the network is already back.

function listenerCount() {
  const listeners = new Map();
  return {
    total: () => [...listeners.values()].reduce((sum, set) => sum + set.size, 0),
    addEventListener(event, listener) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(listener);
    },
    removeEventListener(event, listener) {
      listeners.get(event)?.delete(listener);
    },
  };
}

test("ten canvas mounts leave no listeners behind (#886)", () => {
  const target = listenerCount();
  const surfaceRef = { current: null };

  for (let mount = 0; mount < 10; mount += 1) {
    const renderer = createProtocolRenderer(surfaceRef, target);
    assert.equal(target.total(), 1, "a mount watches for the tab being hidden");
    renderer.dispose();
    assert.equal(target.total(), 0, `mount ${mount} left its listener behind`);
  }
});

test("a renderer disposed twice is not a problem", () => {
  const target = listenerCount();
  const renderer = createProtocolRenderer({ current: null }, target);
  renderer.dispose();
  renderer.dispose();
  assert.equal(target.total(), 0);
});

test("a short alt-tab with an event in it needs no resync", () => {
  assert.equal(shouldResyncOnReturn({ hiddenForMs: 1000, heardWhileHidden: true }), false);
});

test("a long hide, or a quiet one, is worth a soft rebind", () => {
  assert.equal(shouldResyncOnReturn({ hiddenForMs: MAX_GAP_MS, heardWhileHidden: true }), true);
  assert.equal(shouldResyncOnReturn({ hiddenForMs: 1000, heardWhileHidden: false }), true);
});

function watchWithClock() {
  const timers = new Map();
  let next = 1;
  const log = [];
  const watch = createHiddenWatch({
    leave: () => log.push("left"),
    rejoin: () => log.push("rejoined"),
    setTimeout: (handler, delayMs) => {
      const id = next++;
      timers.set(id, { handler, delayMs });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
  });
  return {
    watch,
    log,
    pending: () => [...timers.values()].map((timer) => timer.delayMs),
    fire: () => {
      const [id, timer] = [...timers.entries()][0];
      timers.delete(id);
      timer.handler();
    },
  };
}

test("a tab hidden past the grace leaves the channel and rejoins on return", () => {
  const { watch, log, pending, fire } = watchWithClock();
  watch.noteVisibility(true);
  assert.deepEqual(pending(), [LOBBY_HIDDEN_GRACE_MS]);
  fire();
  assert.deepEqual(log, ["left"]);
  assert.equal(watch.watching, false);

  watch.noteVisibility(false);
  assert.deepEqual(log, ["left", "rejoined"]);
  assert.equal(watch.watching, true);
});

test("a tab shown again before the grace never left, and never rejoins", () => {
  const { watch, log, pending } = watchWithClock();
  watch.noteVisibility(true);
  watch.noteVisibility(false);
  assert.deepEqual(pending(), [], "the timer was cancelled");
  assert.deepEqual(log, []);
  assert.equal(watch.watching, true);
});

test("hiding twice arms one timer, and stopping disarms it", () => {
  const { watch, pending, log } = watchWithClock();
  watch.noteVisibility(true);
  watch.noteVisibility(true);
  assert.equal(pending().length, 1);
  watch.stop();
  assert.deepEqual(pending(), []);
  assert.deepEqual(log, []);
});
