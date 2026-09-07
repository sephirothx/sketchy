import assert from "node:assert/strict";
import test from "node:test";

import { CONNECT_TIMEOUT_MS, DEFAULT_ACK_TIMEOUT_MS, connectionTelemetry, socket, transportsAfterStall } from "../src/lib/socket.ts";

test("the socket prefers WebSocket and actually falls back to polling, inside a bounded time", () => {
  // Listing both transports is not the fallback (#601): only
  // `tryAllTransports` makes the client move on when the first fails to open.
  const opts = socket.io.opts;
  assert.deepEqual(opts.transports, ["websocket", "polling"]);
  assert.equal(opts.tryAllTransports, true);
  assert.equal(socket.io.timeout(), CONNECT_TIMEOUT_MS);
  assert.ok(CONNECT_TIMEOUT_MS < 20_000, "shorter than Engine.IO's default, so a dropped upgrade is not 20 s of nothing");
  assert.ok(CONNECT_TIMEOUT_MS < DEFAULT_ACK_TIMEOUT_MS, "a join pressed during the stall lands on the polling session before its acknowledgement times out");
  assert.equal(opts.autoConnect, false);
});

test("connection telemetry reports the transports this page load opened on", () => {
  const before = connectionTelemetry();
  assert.deepEqual(before.transports, []);
  assert.equal(before.upgrades, 0);
  assert.equal(before.fallbacks, 0);
  assert.equal(before.transport, null);
});

test("a stalled WebSocket attempt (no handshake) puts polling first; a refusal changes nothing", () => {
  const both = ["websocket", "polling"];
  assert.deepEqual(transportsAfterStall(both, false), ["polling", "websocket"]);
  // The engine handshook and the server said no: another transport would be refused the same.
  assert.deepEqual(transportsAfterStall(both, true), both);
  // Already polling first, or no polling to fall back to: nothing to change.
  assert.deepEqual(transportsAfterStall(["polling", "websocket"], false), ["polling", "websocket"]);
  assert.deepEqual(transportsAfterStall(["websocket"], false), ["websocket"]);
});

test("a tab stuck on an update it could not fetch does not open another socket", async () => {
  // #476: the page opens the socket by hand in several places (after the
  // first account read, after a sign-in); once the tab is out of date every
  // one of them must be a no-op, not one more handshake to refuse and close.
  const { markUpdateRequired, resetUpdateRequiredForTests } = await import("../src/lib/updateRequired.ts");
  resetUpdateRequiredForTests();
  markUpdateRequired();
  try {
    socket.connect();
    assert.equal(socket.active, false);
    assert.notEqual(socket.io._readyState, "opening");
  } finally {
    resetUpdateRequiredForTests();
  }
});
