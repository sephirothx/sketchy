import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_NAMED_WINNERS,
  competitionRanks,
  crownOutcome,
  placementLabel,
  rowStartOffsets,
} from "../src/lib/standings.ts";

test("distinct scores count up from one", () => {
  assert.deepEqual(competitionRanks([300, 200, 100]), [1, 2, 3]);
});

test("tied scores share the higher place", () => {
  assert.deepEqual(competitionRanks([300, 300, 100]), [1, 1, 3]);
});

test("the places a tie crowds out are skipped", () => {
  assert.deepEqual(competitionRanks([300, 200, 200, 100]), [1, 2, 2, 4]);
  assert.deepEqual(competitionRanks([300, 300, 300, 100]), [1, 1, 1, 4]);
});

test("everyone level is everyone first", () => {
  assert.deepEqual(competitionRanks([0, 0, 0]), [1, 1, 1]);
});

test("an empty game has no places", () => {
  assert.deepEqual(competitionRanks([]), []);
});

test("medals follow the place, so a shared first awards two golds", () => {
  const ranks = competitionRanks([300, 300, 100]);
  assert.deepEqual(ranks.map(placementLabel), ["🥇", "🥇", "🥉"]);
});

test("places past the podium show as numbers", () => {
  assert.equal(placementLabel(4), "#4");
  assert.equal(placementLabel(11), "#11");
});

test("the client agrees with the server's recorded places", () => {
  // Mirrors tests/test_standings.py: the final screen and the history row must
  // not disagree about whether two players tied.
  assert.deepEqual(competitionRanks([300, 300, 100]), [1, 1, 3]);
  assert.deepEqual(competitionRanks([400, 300, 300, 100]), [1, 2, 2, 4]);
});

test("one winner is crowned, several share the crown", () => {
  assert.equal(crownOutcome(1), "one");
  assert.equal(crownOutcome(2), "shared");
  assert.equal(crownOutcome(MAX_NAMED_WINNERS), "shared");
});

test("past a few winners the headline counts them instead of listing them", () => {
  assert.equal(crownOutcome(MAX_NAMED_WINNERS + 1), "many");
  assert.equal(crownOutcome(16), "many");
});

test("a game with nobody to crown falls back to the room", () => {
  assert.equal(crownOutcome(0), "room");
});

test("the first turn of a game moves no rows, though everyone ranked first", () => {
  // The regression: every player starts on zero, so every previousRank is 1.
  // Offsetting by rank difference shifted rows 2 and 3 up by one and two rows
  // and stacked the whole list on one line.
  const offsets = rowStartOffsets([
    { playerId: "a", previousRank: 1 },
    { playerId: "b", previousRank: 1 },
    { playerId: "c", previousRank: 1 },
  ]);
  assert.deepEqual(offsets, [0, 0, 0]);
});

test("a row that overtook another starts below it and slides up", () => {
  // b was second, is now first; a was first and is now second.
  const offsets = rowStartOffsets([
    { playerId: "b", previousRank: 2 },
    { playerId: "a", previousRank: 1 },
  ]);
  assert.deepEqual(offsets, [1, -1]);
});

test("standings that did not change move nothing", () => {
  const offsets = rowStartOffsets([
    { playerId: "a", previousRank: 1 },
    { playerId: "b", previousRank: 2 },
    { playerId: "c", previousRank: 3 },
  ]);
  assert.deepEqual(offsets, [0, 0, 0]);
});

test("a row never starts outside the list it belongs to", () => {
  // Whatever the ranks, an offset can only move a row to another row's seat.
  const entries = [
    { playerId: "a", previousRank: 1 },
    { playerId: "b", previousRank: 1 },
    { playerId: "c", previousRank: 4 },
    { playerId: "d", previousRank: 4 },
  ];
  rowStartOffsets(entries).forEach((offset, index) => {
    const seat = index + offset;
    assert.ok(seat >= 0 && seat < entries.length, `row ${index} starts at ${seat}`);
  });
});
