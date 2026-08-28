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

test("a fractional window is displayed as whole seconds, never as more time", () => {
  // The server announces exactly what it will wait, fractions included, so a
  // countdown cannot outlive the socket. Rounding for display belongs here -
  // and rounds the *bound*, so it can never show more than is being given.
  const notice = {
    contractVersion: 1,
    reason: "deployment",
    drainSeconds: 1.25,
    startedAt: new Date(1000).toISOString(),
  };
  assert.equal(shutdownSecondsRemaining(notice, 1000), 2);
  assert.equal(shutdownSecondsRemaining(notice, 1500), 1);
  assert.equal(shutdownSecondsRemaining(notice, 3000), 0);
});
