import assert from "node:assert/strict";
import test from "node:test";

import { MAX_LAG_MS, createStrokePlayback } from "../src/lib/strokePlayback.ts";
import { rasterizePath } from "../src/lib/canvasPixels.ts";

const STYLE = { radius: 2, color: [0, 0, 0, 255] };

function playback(interval = 80, maxLagMs) {
  const painted = [];
  const play = createStrokePlayback({
    intervalMs: () => interval,
    paint: (points) => painted.push(points),
    maxLagMs,
  });
  return { play, painted };
}

test("a batch is painted over the interval that follows it, a segment at a time", () => {
  const { play, painted } = playback(80);
  play.enqueueSegments({ x: 0, y: 0 }, [{ x: 10, y: 0 }, { x: 20, y: 0 }, { x: 30, y: 0 }, { x: 40, y: 0 }], STYLE, 1000);
  assert.equal(play.advance(1000), true);
  assert.deepEqual(painted, []);
  assert.equal(play.advance(1040), true);
  // Half way through the interval: two of four segments.
  assert.deepEqual(painted.at(-1), [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 20, y: 0 }]);
  assert.equal(play.advance(1080), false);
  assert.deepEqual(painted.at(-1), [{ x: 20, y: 0 }, { x: 30, y: 0 }, { x: 40, y: 0 }]);
});

test("a frame lands mid-segment and the rest of the segment is painted from there", () => {
  const { play, painted } = playback(100);
  play.enqueueSegments({ x: 0, y: 0 }, [{ x: 100, y: 0 }], STYLE, 0);
  play.advance(30);
  play.advance(70);
  play.advance(100);
  assert.deepEqual(painted, [
    [{ x: 0, y: 0 }, { x: 30, y: 0 }],
    [{ x: 30, y: 0 }, { x: 70, y: 0 }],
    [{ x: 70, y: 0 }, { x: 100, y: 0 }],
  ]);
});

test("batches queue back to back, and the next starts when the previous is due to end", () => {
  const { play, painted } = playback(80);
  play.enqueueSegments({ x: 0, y: 0 }, [{ x: 10, y: 0 }], STYLE, 0);
  // Arrives early: it waits its turn rather than overlapping.
  play.enqueueSegments({ x: 10, y: 0 }, [{ x: 20, y: 0 }], STYLE, 50);
  play.advance(80);
  assert.deepEqual(painted, [[{ x: 0, y: 0 }, { x: 10, y: 0 }]]);
  play.advance(120);
  assert.deepEqual(painted.at(-1), [{ x: 10, y: 0 }, { x: 15, y: 0 }]);
});

test("a barrier runs only once everything before it is painted, and at once when nothing is", () => {
  const { play, painted } = playback(80);
  const ran = [];
  play.enqueueBarrier(() => ran.push("first"), 0);
  assert.deepEqual(ran, ["first"]);
  play.enqueueSegments({ x: 0, y: 0 }, [{ x: 10, y: 0 }], STYLE, 0);
  play.enqueueBarrier(() => ran.push("fill"), 0);
  play.enqueueSegments({ x: 10, y: 0 }, [{ x: 20, y: 0 }], STYLE, 0);
  play.advance(40);
  assert.deepEqual(ran, ["first"]);
  play.advance(80);
  assert.deepEqual(ran, ["first", "fill"], "the fill saw the whole first batch");
  assert.equal(painted.length, 2, "and the second batch has not started before it");
  play.advance(160);
  assert.deepEqual(painted.at(-1), [{ x: 10, y: 0 }, { x: 20, y: 0 }]);
});

test("past the lag bound the schedule is compressed so the viewer catches up", () => {
  const { play, painted } = playback(80, 100);
  for (let batch = 0; batch < 6; batch += 1) {
    play.enqueueSegments({ x: batch * 10, y: 0 }, [{ x: batch * 10 + 10, y: 0 }], STYLE, 0);
  }
  // Six batches at 80 ms would be 480 ms of ink; the bound is 100 ms.
  assert.equal(play.advance(100), false, "everything was due within the bound");
  assert.equal(painted.length, 6);
});

test("drain paints everything at once and cancel paints nothing", () => {
  const { play, painted } = playback(80);
  const ran = [];
  play.enqueueSegments({ x: 0, y: 0 }, [{ x: 10, y: 0 }], STYLE, 0);
  play.enqueueBarrier(() => ran.push("end"), 0);
  play.drain();
  assert.deepEqual(painted, [[{ x: 0, y: 0 }, { x: 10, y: 0 }]]);
  assert.deepEqual(ran, ["end"]);
  assert.equal(play.pending(), false);

  play.enqueueSegments({ x: 0, y: 0 }, [{ x: 10, y: 0 }], STYLE, 0);
  play.cancel();
  assert.equal(play.pending(), false);
  assert.equal(play.advance(1000), false);
  assert.equal(painted.length, 1);
});

test("painting a stroke in arbitrary parts leaves the pixels of painting it whole", () => {
  // The guarantee the playback rests on: a capsule split at a point on its
  // own segment is the union of the two halves.
  const width = 64;
  const height = 48;
  const polyline = [{ x: 4.5, y: 6 }, { x: 30.25, y: 10 }, { x: 31, y: 40.75 }, { x: 58, y: 20 }];
  const whole = new Uint8ClampedArray(width * height * 4).fill(255);
  rasterizePath(whole, width, height, polyline, 3.5, [0, 0, 0, 255], false);

  const inParts = new Uint8ClampedArray(width * height * 4).fill(255);
  const play = createStrokePlayback({
    intervalMs: () => 100,
    paint: (points) => rasterizePath(inParts, width, height, points, 3.5, [0, 0, 0, 255], false),
  });
  play.enqueueSegments(polyline[0], polyline.slice(1), STYLE, 0);
  for (const at of [7, 13, 29, 31, 47, 66, 90, 100]) play.advance(at);
  assert.deepEqual(Array.from(inParts), Array.from(whole));
});

test("the lag bound is a quarter of a second", () => {
  assert.equal(MAX_LAG_MS, 250);
});
