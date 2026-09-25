import assert from "node:assert/strict";
import test from "node:test";

import { TURN_STATS, statisticsLayout } from "../src/lib/profileStats.ts";

const none = {
  gamesPlayed: 0,
  turnsPlayed: 0,
  promptsGuessed: 0,
  drawingsMade: 0,
  reactionsReceived: 0,
};

test("a brand-new player gets no tiles at all", () => {
  assert.deepEqual(statisticsLayout(none), { gameStats: false, turnStats: [] });
});

test("abandoned games alone keep their turn counts, and only those", () => {
  // The projection counts turns from an abandoned game but not a game played,
  // so these are true numbers under a games-played of zero.
  const layout = statisticsLayout({ ...none, turnsPlayed: 3, drawingsMade: 1 });
  assert.equal(layout.gameStats, false);
  assert.deepEqual(layout.turnStats, ["turnsPlayed", "drawingsMade"]);
});

test("a finished game shows everything, zeros included", () => {
  const layout = statisticsLayout({ ...none, gamesPlayed: 1 });
  assert.equal(layout.gameStats, true);
  assert.deepEqual(layout.turnStats, TURN_STATS);
});
