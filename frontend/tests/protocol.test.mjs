import assert from "node:assert/strict";
import test from "node:test";

import {
  PROTOCOL_VERSION,
  handleUpgradeRequired,
} from "../src/lib/protocol.ts";

function fakeStorage(initial = {}) {
  const values = { ...initial };
  return {
    getItem: (key) => (key in values ? values[key] : null),
    setItem: (key, value) => {
      values[key] = String(value);
    },
    values,
  };
}

test("the bundle names a protocol version", () => {
  assert.equal(typeof PROTOCOL_VERSION, "number");
  assert.ok(Number.isInteger(PROTOCOL_VERSION) && PROTOCOL_VERSION >= 1);
});

test("an upgrade notice reloads onto the served build", () => {
  const storage = fakeStorage();
  let reloads = 0;

  const reloaded = handleUpgradeRequired(
    { expected: 2, received: 1 },
    { storage, reload: () => { reloads += 1; } },
  );

  assert.equal(reloaded, true);
  assert.equal(reloads, 1);
});

test("a repeated notice for the same version does not reload again", () => {
  // Without this guard a bundle that fails to update - a proxy ignoring
  // no-cache, a stale service worker - would reload forever, turning a
  // recoverable skew into an unusable page.
  const storage = fakeStorage();
  let reloads = 0;
  let stuck = 0;
  const environment = {
    storage,
    reload: () => { reloads += 1; },
    onStuck: () => { stuck += 1; },
  };

  handleUpgradeRequired({ expected: 2, received: 1 }, environment);
  handleUpgradeRequired({ expected: 2, received: 1 }, environment);
  handleUpgradeRequired({ expected: 2, received: 1 }, environment);

  assert.equal(reloads, 1);
  assert.equal(stuck, 2);
});

test("a notice for a newer server version reloads again", () => {
  // A second deploy while the tab is still open is a different skew, not the
  // same one repeating, so it earns its own reload.
  const storage = fakeStorage();
  let reloads = 0;
  const environment = { storage, reload: () => { reloads += 1; } };

  handleUpgradeRequired({ expected: 2, received: 1 }, environment);
  handleUpgradeRequired({ expected: 3, received: 1 }, environment);

  assert.equal(reloads, 2);
});

test("storage that throws still lets the reload happen", () => {
  const hostile = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
  };
  let reloads = 0;

  handleUpgradeRequired(
    { expected: 2, received: 1 },
    { storage: hostile, reload: () => { reloads += 1; } },
  );

  assert.equal(reloads, 1);
});
