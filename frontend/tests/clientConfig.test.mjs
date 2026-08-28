import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

import {
  DEFAULT_CLIENT_CONFIG,
  applyClientConfig,
  currentClientConfig,
  onClientConfig,
  parseClientConfig,
  resetClientConfig,
} from "../src/lib/clientConfig.ts";

beforeEach(() => {
  resetClientConfig();
});

test("a client with no notice yet runs at the compiled defaults", () => {
  assert.deepEqual(currentClientConfig(), DEFAULT_CLIENT_CONFIG);
});

test("a notice replaces the cadences", () => {
  applyClientConfig({
    contractVersion: 1,
    flushIntervalMs: 56,
    lobbyPollIntervalMs: 8000,
  });
  assert.deepEqual(currentClientConfig(), {
    flushIntervalMs: 56,
    lobbyPollIntervalMs: 8000,
  });
});

test("a subscriber is told what is already known", () => {
  // The notice arrives at the handshake, usually long before anything that
  // depends on it has mounted. A subscriber that only heard about *changes*
  // would miss the value entirely on a page that loads after connecting.
  applyClientConfig({ flushIntervalMs: 72 });
  let seen = null;
  onClientConfig((config) => {
    seen = config;
  });
  assert.equal(seen.flushIntervalMs, 72);
});

test("a subscriber hears about a change", () => {
  const seen = [];
  onClientConfig((config) => seen.push(config.flushIntervalMs));
  applyClientConfig({ flushIntervalMs: 80 });
  assert.deepEqual(seen, [40, 80]);
});

test("re-sending the same values tells nobody", () => {
  // Every reconnect re-sends these. Treating that as a change would tear down
  // and re-arm the drawer's flush timer on every transport bounce.
  const seen = [];
  onClientConfig((config) => seen.push(config.flushIntervalMs));
  applyClientConfig({ flushIntervalMs: 40, lobbyPollIntervalMs: 4000 });
  applyClientConfig({ flushIntervalMs: 40, lobbyPollIntervalMs: 4000 });
  assert.deepEqual(seen, [40]);
});

test("unsubscribing stops the notices", () => {
  const seen = [];
  const stop = onClientConfig((config) => seen.push(config.flushIntervalMs));
  stop();
  applyClientConfig({ flushIntervalMs: 80 });
  assert.deepEqual(seen, [40]);
});

test("a missing field keeps the default rather than becoming undefined", () => {
  const config = parseClientConfig({ flushIntervalMs: 56 });
  assert.equal(config.flushIntervalMs, 56);
  assert.equal(config.lobbyPollIntervalMs, DEFAULT_CLIENT_CONFIG.lobbyPollIntervalMs);
});

test("a nonsense payload leaves the client on its defaults", () => {
  // A server that cannot say is not a reason to stop drawing.
  for (const payload of [undefined, null, "40", 40, [], { flushIntervalMs: "fast" }]) {
    resetClientConfig();
    applyClientConfig(payload);
    assert.deepEqual(currentClientConfig(), DEFAULT_CLIENT_CONFIG, String(payload));
  }
});

test("a value outside what the client can run is refused", () => {
  // Not a second opinion about the right number - the server owns that. This
  // only refuses one that would break the client outright: a zero interval is
  // a busy loop, and an enormous one is a canvas that never updates.
  for (const interval of [0, -40, 5, 5000, Number.NaN, Number.POSITIVE_INFINITY]) {
    resetClientConfig();
    applyClientConfig({ flushIntervalMs: interval });
    assert.equal(
      currentClientConfig().flushIntervalMs,
      DEFAULT_CLIENT_CONFIG.flushIntervalMs,
      String(interval),
    );
  }
});

test("the bounds admit the values the server's own bounds allow", () => {
  for (const interval of [10, 40, 56, 80, 200]) {
    resetClientConfig();
    applyClientConfig({ flushIntervalMs: interval });
    assert.equal(currentClientConfig().flushIntervalMs, interval);
  }
});
