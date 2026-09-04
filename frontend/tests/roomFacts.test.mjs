import assert from "node:assert/strict";
import test from "node:test";

import { estimatedMinutes, roomFacts, roomFactsSummary } from "../src/lib/roomFacts.ts";

const ROOM = {
  playerCount: 5,
  maxPlayers: 8,
  rounds: 3,
  drawingSeconds: 90,
  scoringMode: "default",
  hintMode: "checkpoints",
  hideMaskedPrompt: false,
  allowedTools: ["brush", "fill", "shapes"],
  colorMode: "all",
};

test("six facts, always in the same order", () => {
  // The order is the contract: three surfaces render this list, and a room
  // read in the lobby has to be the same room on the invite page (R-UX-09).
  assert.deepEqual(
    roomFacts(ROOM).map((fact) => fact.key),
    ["players", "rounds", "drawingTime", "scoring", "hints", "drawingRules"],
  );
  assert.deepEqual(
    roomFacts({ ...ROOM, scoringMode: "none", hintMode: "off", rounds: 1 }).map((fact) => fact.key),
    ["players", "rounds", "drawingTime", "scoring", "hints", "drawingRules"],
  );
});

test("every fact carries a label, a value and something to read without one", () => {
  for (const fact of roomFacts(ROOM)) {
    assert.ok(fact.label.length > 0, `${fact.key} has no label`);
    assert.ok(fact.value.length > 0, `${fact.key} has no value`);
    assert.ok(fact.short.length > 0, `${fact.key} has no short form`);
  }
});

test("the seats line counts down and says so when there are none", () => {
  const [players] = roomFacts(ROOM);
  assert.equal(players.value, "5 of 8");
  assert.equal(players.short, "5/8");
  assert.equal(players.detail, "3 seats free");
  assert.equal(roomFacts({ ...ROOM, playerCount: 7 })[0].detail, "1 seat free");
  assert.equal(roomFacts({ ...ROOM, playerCount: 8 })[0].detail, "the room is full");
});

test("one round draws once, three draw three times", () => {
  assert.equal(roomFacts({ ...ROOM, rounds: 1 })[1].short, "1 round");
  assert.equal(roomFacts({ ...ROOM, rounds: 1 })[1].detail, "everyone draws once");
  assert.equal(roomFacts(ROOM)[1].detail, "everyone draws 3 times");
});

test("a room that restricts nothing says so rather than showing a blank", () => {
  const rules = roomFacts(ROOM).at(-1);
  assert.equal(rules.value, "All tools");
  assert.equal(rules.detail, "all colors");
  const limited = roomFacts({ ...ROOM, allowedTools: ["brush"], colorMode: "palette" }).at(-1);
  assert.notEqual(limited.value, "All tools");
  assert.equal(limited.detail, "");
});

test("a hidden prompt overrides whatever the hint mode was", () => {
  const [, , , , hints] = roomFacts({ ...ROOM, hideMaskedPrompt: true });
  assert.equal(hints.value, "Hidden prompt");
  assert.ok(hints.detail.length > 0);
});

test("the estimate grows with players, rounds and drawing time", () => {
  const base = estimatedMinutes(ROOM);
  assert.ok(estimatedMinutes({ ...ROOM, rounds: 6 }) > base);
  assert.ok(estimatedMinutes({ ...ROOM, playerCount: 8 }) > base);
  assert.ok(estimatedMinutes({ ...ROOM, drawingSeconds: 180 }) > base);
  // An empty room is still a two-player game's worth of time, not none.
  assert.equal(estimatedMinutes({ ...ROOM, playerCount: 0 }), estimatedMinutes({ ...ROOM, playerCount: 2 }));
});

test("the summary line is the same facts, in order, minus the count", () => {
  const summary = roomFactsSummary(ROOM);
  assert.equal(summary, "3 rounds · 90s · Default scoring · Timed hints · All tools");
  assert.ok(!summary.includes("5/8"));
  assert.equal(
    roomFactsSummary({ ...ROOM, scoringMode: "none" }).split(" · ")[2],
    "No scoring",
  );
});
