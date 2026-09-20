import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

import {
  DEFAULT_CLIENT_CONFIG,
  applyClientConfig,
  currentClientConfig,
  flushIntervalFor,
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
  applyClientConfig({ contractVersion: 5, flushIntervalMs: 56 });
  assert.deepEqual(currentClientConfig(), {
    flushIntervalMs: 56, pollingFlushIntervalMs: 240, drawingFramesPerWindow: 100,
    drawingWindowSeconds: 2, afkInputWindowMs: 60_000,
  });
});

test("a subscriber is told what is already known", () => {
  // The notice arrives at the handshake, usually long before anything that
  // depends on it has mounted. A subscriber that only heard about *changes*
  // would miss the value entirely on a page that loads after connecting.
  applyClientConfig({ contractVersion: 5, flushIntervalMs: 72 });
  let seen = null;
  onClientConfig((config) => {
    seen = config;
  });
  assert.equal(seen.flushIntervalMs, 72);
});

test("a subscriber hears about a change", () => {
  const seen = [];
  onClientConfig((config) => seen.push(config.flushIntervalMs));
  applyClientConfig({ contractVersion: 5, flushIntervalMs: 72 });
  assert.deepEqual(seen, [80, 72]);
});

test("re-sending the same values tells nobody", () => {
  // Every reconnect re-sends these. Treating that as a change would tear down
  // and re-arm the drawer's flush timer on every transport bounce.
  const seen = [];
  onClientConfig((config) => seen.push(config.flushIntervalMs));
  applyClientConfig({ contractVersion: 5, flushIntervalMs: 40 });
  applyClientConfig({ contractVersion: 5, flushIntervalMs: 40 });
  assert.deepEqual(seen, [80, 40]);
});

test("unsubscribing stops the notices", () => {
  const seen = [];
  const stop = onClientConfig((config) => seen.push(config.flushIntervalMs));
  stop();
  applyClientConfig({ contractVersion: 5, flushIntervalMs: 56 });
  assert.deepEqual(seen, [80]);
});

test("a missing field keeps the default rather than becoming undefined", () => {
  const config = parseClientConfig({ contractVersion: 5 });
  assert.equal(config.flushIntervalMs, DEFAULT_CLIENT_CONFIG.flushIntervalMs);
});

test("a nonsense payload leaves the client on its defaults", () => {
  // A server that cannot say is not a reason to stop drawing.
  for (const payload of [
    undefined,
    null,
    "40",
    40,
    [],
    { contractVersion: 5, flushIntervalMs: "fast" },
  ]) {
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
    applyClientConfig({ contractVersion: 5, flushIntervalMs: interval });
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
    applyClientConfig({ contractVersion: 5, flushIntervalMs: interval });
    assert.equal(currentClientConfig().flushIntervalMs, interval);
  }
});

test("a notice from a contract this build does not know is ignored whole", () => {
  // Not field by field. A later server could give a field a different meaning
  // rather than a different name, and a client that kept the ones it
  // recognised would be running half a contract it does not understand.
  applyClientConfig({ contractVersion: 5, flushIntervalMs: 80 });
  for (const version of [1, 2, 3, 4, 6, 0, "5", undefined, null]) {
    applyClientConfig({ contractVersion: version, flushIntervalMs: 20 });
    assert.equal(currentClientConfig().flushIntervalMs, 80, String(version));
  }
});

test("an unknown contract leaves subscribers undisturbed", () => {
  const seen = [];
  onClientConfig((config) => seen.push(config.flushIntervalMs));
  applyClientConfig({ contractVersion: 99, flushIntervalMs: 20 });
  assert.deepEqual(seen, [80]);
});

test("parsing reports an unknown contract rather than guessing", () => {
  assert.equal(parseClientConfig({ contractVersion: 4, flushIntervalMs: 56 }), null);
  assert.equal(parseClientConfig(undefined), null);
});

test("version 5 carries the drawing allowance and the AFK input window, bounded, with the compiled defaults when absent", () => {
  const config = parseClientConfig({ contractVersion: 5, flushIntervalMs: 40, drawingFramesPerWindow: 200, drawingWindowSeconds: 2 });
  assert.equal(config.drawingFramesPerWindow, 200);
  assert.equal(config.drawingWindowSeconds, 2);
  const absent = parseClientConfig({ contractVersion: 5, flushIntervalMs: 40 });
  assert.equal(absent.drawingFramesPerWindow, 100);
  assert.equal(absent.drawingWindowSeconds, 2);
  const outOfBounds = parseClientConfig({ contractVersion: 5, flushIntervalMs: 40, drawingFramesPerWindow: 5, drawingWindowSeconds: 0 });
  assert.equal(outOfBounds.drawingFramesPerWindow, 100);
  assert.equal(outOfBounds.drawingWindowSeconds, 2);
  // Version 4 (#677): the window a client answers an AFK check inside.
  assert.equal(absent.afkInputWindowMs, 60_000, "compiled default when absent");
  assert.equal(
    parseClientConfig({ contractVersion: 5, flushIntervalMs: 40, afkInputWindowMs: 90_000 }).afkInputWindowMs,
    90_000,
  );
  assert.equal(
    parseClientConfig({ contractVersion: 5, flushIntervalMs: 40, afkInputWindowMs: 1 }).afkInputWindowMs,
    60_000,
    "a window of nothing would ask somebody who is typing",
  );
  assert.equal(parseClientConfig({ contractVersion: 3, flushIntervalMs: 40 }), null, "an older notice is not applied");
});

test("a polling session draws at the polling cadence, and nothing else does (#887)", () => {
  const config = { ...DEFAULT_CLIENT_CONFIG, flushIntervalMs: 80, pollingFlushIntervalMs: 240 };
  assert.equal(flushIntervalFor("polling", config), 240);
  assert.equal(flushIntervalFor("websocket", config), 80);
  // Before a transport is open, and for anything unrecognised, the ordinary
  // cadence: a session that is about to be a WebSocket must not start slow.
  assert.equal(flushIntervalFor(null, config), 80);
  assert.equal(flushIntervalFor(undefined, config), 80);
});

test("a server that names no polling cadence leaves the client on the default", () => {
  const config = parseClientConfig({ contractVersion: 5, flushIntervalMs: 56 });
  assert.equal(config.pollingFlushIntervalMs, DEFAULT_CLIENT_CONFIG.pollingFlushIntervalMs);
});

test("a transport picks a cadence for the hand that draws, never for a viewer (#887)", async () => {
  // Only the drawer's own flush is chosen by its own transport. A viewer
  // paces playback by the interval that produced the batch, which the server
  // states (`drawerFlushIntervalMs`) and the renderer takes as an argument -
  // reaching for a local answer here is how the wrong party's transport got
  // used. See `drawerCadence.test.mjs` for what each mismatch looks like.
  const { readFile } = await import("node:fs/promises");
  const renderer = await readFile(new URL("../src/lib/protocolRenderer.ts", import.meta.url), "utf8");
  assert.doesNotMatch(renderer, /flushIntervalFor|currentTransport|currentClientConfig/);

  const pointer = await readFile(new URL("../src/hooks/useCanvasPointerInput.ts", import.meta.url), "utf8");
  assert.match(pointer, /flushIntervalFor\(transport, config\)/, "the drawer's own flush is by transport");
});
