import assert from "node:assert/strict";
import test from "node:test";

import { dailyMarks, fingerprint, forgetServeStart, serveStartedAt, untilLocalMidnight } from "../src/lib/soloPlay.ts";

function withStorage(run) {
  const kept = new Map();
  const previous = globalThis.localStorage;
  globalThis.localStorage = {
    getItem: (key) => (kept.has(key) ? kept.get(key) : null),
    setItem: (key, value) => kept.set(key, String(value)),
    removeItem: (key) => kept.delete(key),
  };
  try {
    return run(kept);
  } finally {
    globalThis.localStorage = previous;
  }
}

test("a drawing's clock is remembered, so a reload carries on with it", () =>
  withStorage(() => {
    assert.equal(serveStartedAt("s1", "forms", 1_000), 1_000);
    assert.equal(serveStartedAt("s1", "forms", 9_000), 1_000, "the first showing's start");
    forgetServeStart("s1");
    assert.equal(serveStartedAt("s1", "forms", 9_000), 9_000, "forgotten once settled");
  }));

test("a Daily drawing replaced under the same serve gets a clock of its own", () =>
  withStorage(() => {
    serveStartedAt("s2", "the old drawing's forms", 1_000);
    assert.equal(serveStartedAt("s2", "the replacement's forms", 5_000), 5_000);
    assert.notEqual(fingerprint("a"), fingerprint("b"));
  }));

test("a start in the future or unreadable is not trusted, and no storage still plays", () => {
  withStorage((kept) => {
    kept.set("sketchy_solo_started_s3", `99999|${fingerprint("f")}`);
    assert.equal(serveStartedAt("s3", "f", 5_000), 5_000);
    kept.set("sketchy_solo_started_s4", "garbage");
    assert.equal(serveStartedAt("s4", "f", 5_000), 5_000);
  });
  const previous = globalThis.localStorage;
  globalThis.localStorage = {
    getItem: () => {
      throw new Error("refused");
    },
  };
  try {
    assert.equal(serveStartedAt("s5", "f", 7_000), 7_000);
  } finally {
    globalThis.localStorage = previous;
  }
});

test("a Daily reads as five squares in the order it was played", () => {
  const result = (outcomes) => ({ marks: outcomes.map((outcome) => ({ outcome, seconds: 1, late: false })) });
  assert.deepEqual(dailyMarks(result([])), ["unplayed", "unplayed", "unplayed", "unplayed", "unplayed"]);
  assert.deepEqual(dailyMarks(result(["solved", "timed_out", "given_up"])), [
    "solved",
    "missed",
    "missed",
    "unplayed",
    "unplayed",
  ]);
});

test("the next Daily is at the player's own midnight", () => {
  assert.equal(untilLocalMidnight(new Date(2026, 9, 15, 23, 59, 30)), 30_000);
  assert.equal(untilLocalMidnight(new Date(2026, 9, 15, 0, 0, 0)), 24 * 3600 * 1000);
});
