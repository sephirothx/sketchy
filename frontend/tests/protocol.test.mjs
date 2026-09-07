import assert from "node:assert/strict";
import test from "node:test";

import {
  PROTOCOL_VERSION,
  handleProtocolHeader,
  handleUpgradeRequired,
  reloadForUpdate,
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

test("a REST response stamped with another version reloads once, with the same marker", () => {
  // #476: the socket notice and the header share the marker, so between them
  // they cannot reload the page twice for one server version.
  const storage = fakeStorage();
  let reloads = 0;
  let stuck = 0;
  const environment = {
    storage,
    reload: () => { reloads += 1; },
    onStuck: () => { stuck += 1; },
  };

  assert.equal(handleProtocolHeader(String(PROTOCOL_VERSION), environment), false);
  assert.equal(handleProtocolHeader(String(PROTOCOL_VERSION + 1), environment), true);
  assert.equal(reloads, 1);
  handleUpgradeRequired({ expected: PROTOCOL_VERSION + 1, received: PROTOCOL_VERSION }, environment);
  assert.equal(reloads, 1);
  assert.equal(stuck, 1);
});

test("a rollback to an older server version reloads onto it the same way", () => {
  const storage = fakeStorage();
  let reloads = 0;
  handleProtocolHeader(String(PROTOCOL_VERSION - 1), { storage, reload: () => { reloads += 1; } });
  assert.equal(reloads, 1);
});

test("a header that is missing or not a version is not a skew", () => {
  // A proxy stripping unknown headers, or a captive portal answering in the
  // server's place, must not reload the page.
  let reloads = 0;
  const environment = { storage: fakeStorage(), reload: () => { reloads += 1; } };
  for (const value of [null, undefined, "", "abc", "1.5", "-1", "15x"]) {
    assert.equal(handleProtocolHeader(value, environment), false, String(value));
  }
  assert.equal(reloads, 0);
});

test("reloading on request forgets the automatic reload already spent", () => {
  const storage = fakeStorage({ "sketchy:upgrade-reload": "2" });
  let reloads = 0;
  reloadForUpdate({ storage: { removeItem: (key) => { delete storage.values[key]; } }, reload: () => { reloads += 1; } });
  assert.equal(reloads, 1);
  assert.equal(storage.getItem("sketchy:upgrade-reload"), null);
  // So the next notice for that version is acted on again, not reported stuck.
  let stuck = 0;
  handleUpgradeRequired({ expected: 2, received: 1 }, { storage, reload: () => { reloads += 1; }, onStuck: () => { stuck += 1; } });
  assert.equal(reloads, 2);
  assert.equal(stuck, 0);
});
