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
  attemptIsInFlight,
  shouldReconnectImmediately,
  STALL_INTERVAL_MS,
  shutdownHoldMs,
  stallRecovery,
  transportAlive,
  SERVER_CLOSE_RETRY_BASE_MS,
  SERVER_CLOSE_RETRY_MAX_MS,
  SERVER_FULL_RETRY_MS,
  serverCloseRetryDelayMs,
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
  assert.equal(
    shouldReconnectImmediately({ ...state, attemptInFlight: true }),
    false,
    "reopening closes first, and closing would abort the handshake under way",
  );
});

test("an attempt is in flight however it was opened, not only on a retry", () => {
  // The gap the first version had: `attemptInFlight` was set from
  // `reconnect_attempt`, which three paths never emit - the first connect,
  // the stall watchdog's reopen, and `reconnectWithCurrentIdentity`. Against
  // a blackholed address a manual open sits at `opening` with no such event,
  // so the guard was absent on exactly the network that flaps. The manager's
  // own ready state is set inside `open()`, so it covers all of them.
  assert.equal(attemptIsInFlight("opening"), true, "a manual open is an attempt");
  assert.equal(attemptIsInFlight("open"), true, "the namespace connect is still a round trip");
  assert.equal(attemptIsInFlight("closed"), false);
  assert.equal(attemptIsInFlight(undefined), false, "no manager, nothing to interrupt");
});

test("the network-return handler reads the manager, not the retry event", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(new URL("../src/lib/socket.ts", import.meta.url), "utf8");
  assert.match(source, /attemptInFlight: attemptIsInFlight\(managerReadyState\(\)\)/);
});

test("a flapping interface does not interrupt the handshake it keeps asking for", () => {
  // Wi-Fi that drops and returns fires `online` each time. Reopening means
  // `disconnect()` then `connect()` - the close is what cancels the pending
  // retry - so without the in-flight guard each event would abort the attempt
  // the one before it started, and none would ever finish.
  let inFlight = false;
  let opened = 0;
  const bounce = () => {
    if (!shouldReconnectImmediately({
      connected: false, updateRequired: false, restartExpected: false,
      attemptInFlight: inFlight,
    })) return;
    opened += 1;
    inFlight = true;
  };

  bounce();
  bounce();
  bounce();
  assert.equal(opened, 1, "three `online` events, one attempt");
});

test("a phase that overran its clock costs a soft rebind while the server is only slow (#1009)", () => {
  const first = { escalations: 0, notBefore: 0, now: 1000, random: 0.5 };
  assert.equal(stallRecovery({ ...first, transportAlive: true, restartApproved: false }).action, "soft");
  assert.equal(stallRecovery({ ...first, transportAlive: false, restartApproved: false }).action, "restart");
  // A passed restart vote leaves the game with no phase to be late in, and
  // does not count as a recovery.
  assert.deepEqual(stallRecovery({ ...first, transportAlive: true, restartApproved: true }), {
    action: "none", escalations: 0, notBefore: 0,
  });
});

test("stall recoveries back off like the heartbeat's escalations (#1009)", () => {
  let state = { escalations: 0, notBefore: 0 };
  const gaps = [];
  let now = 0;
  for (let i = 0; i < 5; i += 1) {
    const next = stallRecovery({ ...state, now, random: 0.5, transportAlive: true, restartApproved: false });
    assert.equal(next.action, "soft");
    gaps.push(next.notBefore - now);
    state = { escalations: next.escalations, notBefore: next.notBefore };
    // Asking again before its time is nothing, and does not escalate further.
    const early = stallRecovery({ ...state, now: now + 1, random: 0.5, transportAlive: true, restartApproved: false });
    assert.equal(early.action, "none");
    assert.equal(early.escalations, next.escalations);
    now = next.notBefore;
  }
  assert.deepEqual(gaps, [STALL_INTERVAL_MS, 20_000, 40_000, 60_000, 60_000]);
  // ±50% jitter around the base.
  assert.equal(stallRecovery({ escalations: 0, notBefore: 0, now: 0, random: 0, transportAlive: true, restartApproved: false }).notBefore, STALL_INTERVAL_MS / 2);
  assert.equal(stallRecovery({ escalations: 0, notBefore: 0, now: 0, random: 1, transportAlive: true, restartApproved: false }).notBefore, STALL_INTERVAL_MS * 1.5);
});

test("a socket the server closed is reopened, on a backoff, unless the close was final (#998)", () => {
  const closed = (attempt, extra = {}) =>
    serverCloseRetryDelayMs({
      reason: "io server disconnect",
      attempt,
      updateRequired: false,
      turnedAwayForCapacity: false,
      random: 0.5,
      ...extra,
    });
  // Another tab took the seat, a kick, a stale socket: come back.
  assert.equal(closed(0), SERVER_CLOSE_RETRY_BASE_MS);
  assert.equal(closed(1), 2 * SERVER_CLOSE_RETRY_BASE_MS);
  assert.equal(closed(10), SERVER_CLOSE_RETRY_MAX_MS);
  // ±50% jitter around the step.
  assert.equal(closed(0, { random: 0 }), SERVER_CLOSE_RETRY_BASE_MS / 2);
  assert.equal(closed(0, { random: 1 }), SERVER_CLOSE_RETRY_BASE_MS * 1.5);
  // Told it was full: the server said a few minutes, so the first try waits.
  assert.equal(closed(0, { turnedAwayForCapacity: true }), SERVER_FULL_RETRY_MS);
  // A stale build was closed on purpose and would only be closed again.
  assert.equal(closed(0, { updateRequired: true }), null);
  // This client closing its own socket, or a transport drop, is the
  // manager's business, not this policy's.
  assert.equal(closed(0, { reason: "io client disconnect" }), null);
  assert.equal(closed(0, { reason: "transport close" }), null);
  assert.equal(closed(0, { reason: "ping timeout" }), null);
});

test("a server close is not retried while this page reloads onto a new build (#1056)", () => {
  const closed = {
    reason: "io server disconnect",
    attempt: 0,
    updateRequired: false,
    turnedAwayForCapacity: false,
    random: 0.5,
  };
  assert.notEqual(serverCloseRetryDelayMs(closed), null);
  assert.equal(serverCloseRetryDelayMs({ ...closed, reloadPending: true }), null);
});
