import assert from "node:assert/strict";
import test from "node:test";

import { parseShutdownNotice, shutdownSecondsRemaining } from "../src/lib/shutdownNotice.ts";

const notice = {
  contractVersion: 1,
  reason: "deployment",
  drainSeconds: 30,
  startedAt: "2026-08-23T12:00:00+00:00",
};

test("the current deployment notice is accepted as sent", () => {
  assert.deepEqual(parseShutdownNotice(notice), notice);
});

test("a zero-second window is a real window, not a missing one", () => {
  assert.deepEqual(parseShutdownNotice({ ...notice, drainSeconds: 0 }), {
    ...notice,
    drainSeconds: 0,
  });
});

test("a later contract version is ignored rather than half-rendered", () => {
  assert.equal(parseShutdownNotice({ ...notice, contractVersion: 2 }), null);
});

test("only a deployment is announced as a deployment", () => {
  assert.equal(parseShutdownNotice({ ...notice, reason: "maintenance" }), null);
});

test("a malformed or absent payload never opens the banner", () => {
  for (const payload of [
    null,
    undefined,
    "server_shutdown",
    {},
    { ...notice, drainSeconds: "30" },
    { ...notice, drainSeconds: Number.NaN },
    { ...notice, drainSeconds: -1 },
    { ...notice, startedAt: 1234 },
  ]) {
    assert.equal(parseShutdownNotice(payload), null);
  }
});

test("the countdown starts from the window the server announced", () => {
  const started = Date.parse("2026-08-24T12:00:00+00:00");
  const drain = { ...notice, drainSeconds: 30, startedAt: "2026-08-24T12:00:00+00:00" };

  assert.equal(shutdownSecondsRemaining(drain, started), 30);
  assert.equal(shutdownSecondsRemaining(drain, started + 10_000), 20);
  assert.equal(shutdownSecondsRemaining(drain, started + 29_500), 1);
});

test("the countdown stops at zero rather than going negative", () => {
  const started = Date.parse("2026-08-24T12:00:00+00:00");
  const drain = { ...notice, drainSeconds: 30, startedAt: "2026-08-24T12:00:00+00:00" };

  assert.equal(shutdownSecondsRemaining(drain, started + 30_000), 0);
  assert.equal(shutdownSecondsRemaining(drain, started + 90_000), 0);
});

test("a browser clock ahead of the server cannot promise extra time", () => {
  const started = Date.parse("2026-08-24T12:00:00+00:00");
  const drain = { ...notice, drainSeconds: 30, startedAt: "2026-08-24T12:00:00+00:00" };

  // Client clock five minutes behind: the naive answer would be 330 seconds.
  assert.equal(shutdownSecondsRemaining(drain, started - 300_000), 30);
});

test("an unparseable timestamp falls back to the announced window", () => {
  assert.equal(
    shutdownSecondsRemaining({ ...notice, drainSeconds: 45, startedAt: "not a date" }),
    45,
  );
});

test("a fractional window counts down in whole seconds and reaches zero on time", () => {
  // The server announces exactly what it will wait, fractions included; whole
  // seconds are this side's business. Rounding up means the number can read a
  // little high - 2 while 1.25 remain - which is what a countdown does. The
  // property that matters is the other one: it hits zero when the window
  // closes and not after, so the banner never claims time the socket has
  // already lost. Rounding down would buy the first property and break this
  // one, showing 0 while the server was still waiting.
  const notice = {
    contractVersion: 1,
    reason: "deployment",
    drainSeconds: 1.25,
    startedAt: new Date(1000).toISOString(),
  };
  assert.equal(shutdownSecondsRemaining(notice, 1000), 2);
  assert.equal(shutdownSecondsRemaining(notice, 1500), 1);
  // Still counting at the last instant before the deadline...
  assert.equal(shutdownSecondsRemaining(notice, 2249), 1);
  // ...and zero exactly on it, rather than a moment later.
  assert.equal(shutdownSecondsRemaining(notice, 2250), 0);
  assert.equal(shutdownSecondsRemaining(notice, 3000), 0);
});

test("a clock running behind cannot show more than the announced window", () => {
  // The deadline is the server's, measured against a clock this browser does
  // not share. The clamp is what stops a skewed one promising time that was
  // never offered.
  const notice = {
    contractVersion: 1,
    reason: "deployment",
    drainSeconds: 1.25,
    startedAt: new Date(10_000).toISOString(),
  };
  assert.equal(shutdownSecondsRemaining(notice, 0), 2);
});
