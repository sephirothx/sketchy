import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import {
  MAX_NAMED_WINNERS,
  competitionRanks,
  ENTRANCE_STAGGER_MS,
  crownOutcome,
  entranceDelays,
  hasPreviousOrder,
  placementLabel,
  reorderHoldMs,
  rowStartOffsets,
  shownStanding,
  waitsAtOldPlace,
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

test("the first turn has no previous order to rearrange from", () => {
  // Everyone comes in on zero, so everyone shares first place.
  assert.equal(
    hasPreviousOrder([
      { previousRank: 1 },
      { previousRank: 1 },
      { previousRank: 1 },
    ]),
    false,
  );
});

test("once anyone is ahead there is an order to rearrange", () => {
  assert.equal(
    hasPreviousOrder([{ previousRank: 1 }, { previousRank: 2 }]),
    true,
  );
  // A tie further down still counts: someone is ahead of it.
  assert.equal(
    hasPreviousOrder([
      { previousRank: 1 },
      { previousRank: 2 },
      { previousRank: 2 },
    ]),
    true,
  );
});

test("rows enter lowest place first, building up to the leader", () => {
  const delays = entranceDelays(3);
  // Index 0 is the leader, so it waits the longest; the last row starts at once.
  assert.deepEqual(delays, [2 * ENTRANCE_STAGGER_MS, ENTRANCE_STAGGER_MS, 0]);
  assert.equal(delays[delays.length - 1], 0);
  assert.ok(delays[0] > delays[delays.length - 1]);
});

test("a lone player waits for nobody", () => {
  assert.deepEqual(entranceDelays(1), [0]);
  assert.deepEqual(entranceDelays(0), []);
});

test("a waiting row shows the place and total it came in with, and a settled one the new (#1278)", () => {
  // Hostina overtakes Deskar: new order first, as the card sorts them.
  const entries = [
    { playerId: "p", previousRank: 1, newRank: 1, score: 1165, delta: 40 },
    { playerId: "h", previousRank: 3, newRank: 2, score: 1130, delta: 130 },
    { playerId: "d", previousRank: 2, newRank: 3, score: 1115, delta: 0 },
  ];
  const offsets = rowStartOffsets(entries);
  // Where each row stands while it waits, top to bottom: its number there
  // must be its place there.
  const waiting = entries
    .map((entry, index) => ({ row: index + offsets[index], ...shownStanding(entry, true) }))
    .sort((a, b) => a.row - b.row);
  assert.deepEqual(waiting.map(({ rank }) => rank), [1, 2, 3]);
  assert.deepEqual(waiting.map(({ total }) => total), [1125, 1115, 1000]);
  assert.deepEqual(
    entries.map((entry) => shownStanding(entry, false)),
    [{ rank: 1, total: 1165 }, { rank: 2, total: 1130 }, { rank: 3, total: 1115 }],
  );
});

test("rows wait at their old place only while rearranging, before the slide, with motion (review of #1278)", () => {
  assert.equal(waitsAtOldPlace(true, false, false), true);
  // Slid: the new numbers.
  assert.equal(waitsAtOldPlace(true, true, false), false);
  // Introduced rather than rearranged: nothing old to show.
  assert.equal(waitsAtOldPlace(false, false, false), false);
  // Reduced motion puts the rows in their new order at once, so their
  // numbers must be the new ones at once too.
  assert.equal(waitsAtOldPlace(true, false, true), false);
});

test("the wait before the slide is two seconds, or less of a short phase", () => {
  assert.equal(reorderHoldMs(5), 2000);
  assert.equal(reorderHoldMs(0), 2000);
  assert.equal(reorderHoldMs(2), 800);
  assert.equal(reorderHoldMs(0.5), 200);
});

test("every score on screen is written in the locale's numbers (#1279)", async () => {
  // The game-over card said "1,182 points" in its sentence and "1182" on the
  // podium, in its rows and in the standings panel beside it.
  const { EN } = await import("../src/content/ui/en.ts");
  const { DE } = await import("../src/content/ui/de.ts");
  assert.equal(EN.format.number({ value: 1182 }), "1,182");
  assert.equal(DE.format.number({ value: 1182 }), "1.182");
  // A catalogue key (`ui.profilePage.totalScore`) is a label, not a score.
  const raw = /\{\s*(?!ui\.)[A-Za-z_.]*\.(score|finalScore|totalScore)\s*\}|String\([^)]*[sS]core\b/;
  const offenders = [];
  for (const dir of ["components", "pages"]) {
    const root = join(import.meta.dirname, "../src", dir);
    for (const file of readdirSync(root, { recursive: true })) {
      if (!String(file).endsWith(".tsx")) continue;
      readFileSync(join(root, String(file)), "utf8").split("\n").forEach((line, index) => {
        if (raw.test(line)) offenders.push(`${dir}/${file}:${index + 1} ${line.trim()}`);
      });
    }
  }
  assert.deepEqual(offenders, [], `a score printed as a bare number:\n${offenders.join("\n")}`);
});
