import assert from "node:assert/strict";
import test from "node:test";

import {
  abandonmentRate,
  seriesFor,
  sparklinePoints,
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

test("a sparkline puts the biggest value at the top of the box", () => {
  const points = sparklinePoints(
    [
      { date: "a", value: 0 },
      { date: "b", value: 10 },
    ],
    100,
    40,
  ).split(" ");

  // SVG y grows downward, so the peak has to sit at 0 and the trough at the
  // full height - inverting this is the classic upside-down chart.
  assert.equal(points[0], "0,40");
  assert.equal(points[1], "100,0");
});

test("a sparkline with nothing in it draws nothing", () => {
  assert.equal(sparklinePoints([], 100, 40), "");
});

test("a single day is drawn flat rather than at the edge", () => {
  assert.equal(sparklinePoints([{ date: "a", value: 7 }], 100, 40), "0,20 100,20");
});
