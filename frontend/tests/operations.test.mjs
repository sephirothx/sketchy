import assert from "node:assert/strict";
import test from "node:test";

import {
  abandonmentRate,
  seriesFor,
} from "../src/lib/operations.ts";

const days = [
  { date: "2026-08-24", metric: "game.finished", occurrences: 5, valueSum: 0, valueMax: null },
  { date: "2026-08-22", metric: "game.finished", occurrences: 1, valueSum: 0, valueMax: null },
  { date: "2026-08-23", metric: "game.abandoned", occurrences: 9, valueSum: 0, valueMax: null },
  { date: "2026-08-23", metric: "game.finished", occurrences: 3, valueSum: 0, valueMax: null },
];

test("a series is one metric, oldest first", () => {
  // The API answers newest-first because that is what a table wants; a chart
  // reads the other way, and mixing them up draws time backwards.
  assert.deepEqual(seriesFor(days, "game.finished"), [
    { date: "2026-08-22", value: 1 },
    { date: "2026-08-23", value: 3 },
    { date: "2026-08-24", value: 5 },
  ]);
  assert.deepEqual(seriesFor(days, "nothing.recorded"), []);
});

test("abandonment is a share, because the count alone says nothing", () => {
  // Ten abandoned out of twelve is a problem; out of a thousand it is a Tuesday.
  assert.equal(abandonmentRate({ finished: 90, abandoned: 10, shutdown: 0 }), 10);
  assert.equal(abandonmentRate({ finished: 2, abandoned: 10, shutdown: 0 }), 83.3);
  assert.equal(abandonmentRate({ finished: 0, abandoned: 0, shutdown: 0 }), null);
});
