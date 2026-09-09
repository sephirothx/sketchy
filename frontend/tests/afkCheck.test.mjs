import assert from "node:assert/strict";
import test from "node:test";

import {
  COUNTDOWN_TICK_MS,
  INPUT_EVENTS,
  hasLapsed,
  parseAfkCheck,
  respondToCheck,
  secondsLeft,
} from "../src/lib/afkCheck.ts";
import {
  CLIENT_CONFIG_CONTRACT_VERSION,
  DEFAULT_CLIENT_CONFIG,
  parseClientConfig,
} from "../src/lib/clientConfig.ts";

const NOW = 1_700_000_000_000;
const WINDOW = 60_000;
const CHECK = { seconds: 25 };

test("a check the server did not ask is not answered", () => {
  for (const payload of [null, undefined, "check", {}, { seconds: "25" }]) {
    assert.equal(parseAfkCheck(payload), null);
  }
  // A zero or negative window is a countdown with nothing to count.
  assert.equal(parseAfkCheck({ seconds: 0 }), null);
  assert.equal(parseAfkCheck({ seconds: -5 }), null);
  assert.deepEqual(parseAfkCheck({ seconds: 25 }), { seconds: 25 });
});

test("a client that has seen a hand answers without troubling the player", () => {
  const response = respondToCheck(CHECK, {
    now: NOW,
    lastInputAt: NOW - 30_000,
    inputWindowMs: WINDOW,
  });
  assert.deepEqual(response, { kind: "answer" });
});

test("input exactly at the edge of the window still answers", () => {
  const response = respondToCheck(CHECK, {
    now: NOW,
    lastInputAt: NOW - WINDOW,
    inputWindowMs: WINDOW,
  });
  assert.equal(response.kind, "answer");
});

test("a client whose last input is older than the window asks", () => {
  const response = respondToCheck(CHECK, {
    now: NOW,
    lastInputAt: NOW - WINDOW - 1,
    inputWindowMs: WINDOW,
  });
  assert.deepEqual(response, { kind: "ask", deadline: NOW + 25_000 });
});

test("a tab opened and left has seen nothing at all, and asks", () => {
  const response = respondToCheck(CHECK, {
    now: NOW,
    lastInputAt: null,
    inputWindowMs: WINDOW,
  });
  assert.equal(response.kind, "ask");
});

test("the deadline follows the seconds the server named, not a constant", () => {
  const response = respondToCheck(
    { seconds: 8 },
    { now: NOW, lastInputAt: null, inputWindowMs: WINDOW },
  );
  assert.equal(response.deadline, NOW + 8_000);
});

test("the countdown starts at the full number and ends at zero", () => {
  const deadline = NOW + 25_000;
  assert.equal(secondsLeft(deadline, NOW), 25, "not 24 before a frame passed");
  assert.equal(secondsLeft(deadline, NOW + 1), 25);
  assert.equal(secondsLeft(deadline, NOW + 24_001), 1);
  assert.equal(secondsLeft(deadline, deadline), 0);
  assert.equal(secondsLeft(deadline, deadline + 5_000), 0, "never negative");
});

test("a check lapses only once its deadline is reached", () => {
  const deadline = NOW + 25_000;
  assert.equal(hasLapsed(deadline, deadline - 1), false);
  assert.equal(hasLapsed(deadline, deadline), true);
});

test("the input events are the ones a person causes", () => {
  assert.ok(INPUT_EVENTS.includes("keydown"));
  assert.ok(INPUT_EVENTS.includes("pointerdown"));
  // `visibilitychange` is deliberately not here: hiding a tab is not a
  // reason to be marked, and returning to one is not proof anybody is there.
  assert.ok(!INPUT_EVENTS.includes("visibilitychange"));
  assert.ok(COUNTDOWN_TICK_MS > 0 && COUNTDOWN_TICK_MS <= 1000);
});

test("the input window rides the client config the server ships", () => {
  const config = parseClientConfig({
    contractVersion: CLIENT_CONFIG_CONTRACT_VERSION,
    flushIntervalMs: 80,
    drawingFramesPerWindow: 100,
    drawingWindowSeconds: 2,
    afkInputWindowMs: 90_000,
  });
  assert.equal(config.afkInputWindowMs, 90_000);
});

test("an out-of-bounds input window falls back rather than defeating the check", () => {
  const config = parseClientConfig({
    contractVersion: CLIENT_CONFIG_CONTRACT_VERSION,
    flushIntervalMs: 80,
    drawingFramesPerWindow: 100,
    drawingWindowSeconds: 2,
    afkInputWindowMs: 60 * 60 * 1000,
  });
  assert.equal(
    config.afkInputWindowMs,
    DEFAULT_CLIENT_CONFIG.afkInputWindowMs,
    "an hour-long window would answer for somebody who left",
  );
});
