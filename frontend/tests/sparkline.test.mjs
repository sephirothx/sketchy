import assert from "node:assert/strict";
import test from "node:test";

import { sparklinePath, sparklineSummary } from "../src/lib/sparkline.ts";

test("nothing recorded draws nothing", () => {
  assert.equal(sparklinePath([]), "");
  assert.equal(sparklinePath([null, null, null]), "");
  assert.deepEqual(sparklineSummary([null, null]), { last: null, max: null });
});

test("a gap in the data breaks the line rather than bridging it", () => {
  // A minute nobody recorded is not a minute of zero; drawing through it
  // would invent a value.
  const path = sparklinePath([1, 2, null, 4, 5], 100, 20, 0);
  const moves = path.split(" ").filter((token) => token.startsWith("M"));
  assert.equal(moves.length, 2, path);
  assert.match(path, /^M0 \S+ L25 \S+ M75 \S+ L100 \S+$/);
});

test("a flat series sits where its value is, and an all-zero one on the floor", () => {
  // The scale always includes zero, so three-of-three is the top of the
  // chart and nothing is drawn as if it were half of something.
  assert.equal(sparklinePath([3, 3, 3], 100, 20, 0), "M0 0 L50 0 L100 0");
  assert.equal(sparklinePath([0, 0, 0], 100, 20, 0), "M0 10 L50 10 L100 10");
});

test("the summary names the latest value and the worst one", () => {
  assert.deepEqual(sparklineSummary([1, 9, null, 4, null]), { last: 4, max: 9 });
});

test("the scale includes zero so a small dip does not look like a crash", () => {
  const path = sparklinePath([100, 90], 100, 20, 0);
  // 90 of 100 sits near the top, not on the floor.
  assert.equal(path, "M0 0 L100 2");
});
