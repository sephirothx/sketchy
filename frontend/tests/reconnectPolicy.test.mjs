import assert from "node:assert/strict";
import test from "node:test";

import {
  ESCALATION_BASE_MS,
  ESCALATION_MAX_MS,
  MAX_SHUTDOWN_HOLD_MS,
  POST_RECONNECT_JITTER_MS,
  escalateHeartbeat,
  postReconnectDelayMs,
  DEFAULT_PING_WINDOW_MS,
  afterFailedRebind,
  createRestartLatch,
  pingWindowMs,
  shouldReconnectImmediately,
  shutdownHoldMs,
  transportAlive,
} from "../src/lib/reconnectPolicy.ts";

test("the hold after a shutdown is a uniform draw across the window the server named", () => {
  assert.equal(shutdownHoldMs(10_000, 0), 0);
  assert.equal(shutdownHoldMs(10_000, 0.5), 5000);
  assert.equal(shutdownHoldMs(10_000, 0.9999), 9999);
  // Spread over many clients, the draw covers the window evenly.
  const holds = Array.from({ length: 1000 }, (_, i) => shutdownHoldMs(10_000, i / 1000));
  const firstSecond = holds.filter((hold) => hold < 1000).length;
  assert.equal(firstSecond, 100, "a tenth of the clients in the first tenth of the window");
});

test("a missing, broken or absurd spread holds nothing, or no more than the cap", () => {
  for (const spread of [undefined, null, "10000", Number.NaN, -1, 0]) {
    assert.equal(shutdownHoldMs(spread, 0.7), 0);
  }
  assert.equal(shutdownHoldMs(10 * MAX_SHUTDOWN_HOLD_MS, 0.5), MAX_SHUTDOWN_HOLD_MS / 2);
  assert.equal(shutdownHoldMs(10_000, 7), 10_000, "randomness outside [0, 1] is clamped");
});

test("only a reconnect's refetches are spread", () => {
  assert.equal(postReconnectDelayMs(false, 0.9), 0);
  assert.equal(postReconnectDelayMs(true, 0.5), POST_RECONNECT_JITTER_MS / 2);
});

test("the transport is alive while Engine.IO pings keep arriving", () => {
  assert.equal(transportAlive(null, 1000, 45_000), false);
  assert.equal(transportAlive(0, 45_000, 45_000), true);
  assert.equal(transportAlive(0, 45_001, 45_000), false);
  assert.equal(pingWindowMs(10_000, 5000), 15_000);
  assert.equal(pingWindowMs(-1, -1), DEFAULT_PING_WINDOW_MS, "before the handshake says");
  assert.equal(pingWindowMs(undefined, 5000), DEFAULT_PING_WINDOW_MS);
});

const failing = (overrides = {}) => ({
  failures: 3,
  escalations: 0,
  notBefore: 0,
  now: 100_000,
  transportAlive: true,
  random: 0.5,
  ...overrides,
});

test("nothing happens before three misses in a row, or before the backoff allows", () => {
  assert.equal(escalateHeartbeat(failing({ failures: 2 })).action, "none");
  assert.equal(escalateHeartbeat(failing({ notBefore: 100_001 })).action, "none");
});

test("a slow server gets a soft rebind; only a silent transport is restarted", () => {
  assert.equal(escalateHeartbeat(failing()).action, "soft-rebind");
  assert.equal(escalateHeartbeat(failing({ transportAlive: false })).action, "restart");
});

test("each escalation pushes the next one out, doubling to a minute, with jitter", () => {
  let state = { escalations: 0, notBefore: 0 };
  const gaps = [];
  let now = 0;
  for (let i = 0; i < 6; i += 1) {
    now = Math.max(now, state.notBefore);
    const next = escalateHeartbeat(failing({ ...state, now, random: 0.5 }));
    gaps.push(next.notBefore - now);
    state = next;
  }
  assert.deepEqual(gaps, [5000, 10_000, 20_000, 40_000, 60_000, 60_000]);
  assert.equal(gaps[0], ESCALATION_BASE_MS);
  assert.equal(gaps.at(-1), ESCALATION_MAX_MS);
  // ±50%: the same step on two clients lands anywhere in [0.5, 1.5] of it.
  assert.equal(escalateHeartbeat(failing({ random: 0 })).notBefore - 100_000, 2500);
  assert.equal(escalateHeartbeat(failing({ random: 1 })).notBefore - 100_000, 7500);
});

test("a heartbeat's failed soft rebind keeps a live transport; nothing else does", () => {
  assert.equal(afterFailedRebind({ keepTransport: true, transportAlive: true }), "keep");
  assert.equal(afterFailedRebind({ keepTransport: true, transportAlive: false }), "restart");
  assert.equal(afterFailedRebind({ keepTransport: false, transportAlive: true }), "restart");
});

test("a planned restart holds every way back, whichever side closed the socket", () => {
  const latch = createRestartLatch();
  assert.equal(latch.noteClose(0, 0.5), 0, "no notice, no hold");
  latch.noteConnect();

  latch.noteNotice(10_000);
  assert.equal(latch.restartExpected(), false, "announced, still connected");
  // The client closes first during the drain (a phase stall, say).
  assert.equal(latch.noteClose(1000, 0.5), 5000);
  assert.equal(latch.restartExpected(), true);
  assert.equal(latch.holdRemainingMs(3000), 3000);
  // A second close in the same outage keeps the one draw.
  assert.equal(latch.noteClose(4000, 0.99), 2000);
  assert.equal(latch.holdRemainingMs(6000), 0);
  latch.noteConnect();
  assert.equal(latch.restartExpected(), false);
  assert.equal(latch.noteClose(7000, 0.5), 0, "cleared by the replacement connection");
});

test("a notice at a handshake mid-drain survives that connection landing", () => {
  const latch = createRestartLatch();
  latch.noteNotice(8000);
  latch.noteConnect();
  assert.equal(latch.noteClose(0, 0.25), 2000);
});

test("a network coming back connects now - unless a restart's hold is still running (#886)", () => {
  const state = { connected: false, updateRequired: false, restartExpected: false };
  assert.equal(shouldReconnectImmediately(state), true);
  assert.equal(shouldReconnectImmediately({ ...state, connected: true }), false);
  assert.equal(shouldReconnectImmediately({ ...state, updateRequired: true }), false);
  assert.equal(
    shouldReconnectImmediately({ ...state, restartExpected: true }),
    false,
    "a device waking mid-deploy must not jump the spread",
  );
});
