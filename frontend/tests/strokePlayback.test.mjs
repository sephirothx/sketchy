import assert from "node:assert/strict";
import test from "node:test";

import { MAX_LAG_MS, createStrokePlayback } from "../src/lib/strokePlayback.ts";
import { rasterizePath, rasterizeSpans } from "../src/lib/canvasPixels.ts";

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
  // The guarantee the playback rests on: the spans a frame at a time hands
  // over tile each segment, and paint exactly its pixels (#940).
  const width = 64;
  const height = 48;
  const polyline = [{ x: 4.5, y: 6 }, { x: 30.25, y: 10 }, { x: 31, y: 40.75 }, { x: 58, y: 20 }];
  const whole = new Uint8ClampedArray(width * height * 4).fill(255);
  rasterizePath(whole, width, height, polyline, 3.5, [0, 0, 0, 255], false);

  const inParts = new Uint8ClampedArray(width * height * 4).fill(255);
  const play = createStrokePlayback({
    intervalMs: () => 100,
    paint: (_points, _style, spans) => rasterizeSpans(inParts, width, height, spans, 3.5, [0, 0, 0, 255]),
  });
  play.enqueueSegments(polyline[0], polyline.slice(1), STYLE, 0);
  for (const at of [7, 13, 29, 31, 47, 66, 90, 100]) play.advance(at);
  assert.deepEqual(Array.from(inParts), Array.from(whole));
});

test("the lag bound is a quarter of a second", () => {
  assert.equal(MAX_LAG_MS, 250);
});

test("a segment painted in parts is the whole segment's raster, edge pixels included (#940)", () => {
  const size = 40;
  const blank = () => {
    const data = new Uint8ClampedArray(size * size * 4);
    data.fill(255);
    return data;
  };
  const ink = [0, 0, 0, 255];
  // Width 13 along x = 14: column 20's centre is exactly 6.5 across, a tie.
  // Split at 73%, the interpolated point is (14, 7.087500000000002), and a
  // tie-break read off the projection's dust dropped pixel (20, 12).
  const from = { x: 14, y: 26.25 };
  const to = { x: 14, y: 0 };
  const whole = blank();
  rasterizePath(whole, size, size, [from, to], 6.5, ink, false);

  const parts = blank();
  const playback = createStrokePlayback({
    intervalMs: () => 100,
    paint: (_points, style, spans) => rasterizeSpans(parts, size, size, spans, style.radius, style.color),
  });
  playback.enqueueSegments(from, [to], { radius: 6.5, color: ink }, 0);
  playback.advance(73);
  playback.drain();

  assert.deepEqual(parts, whole);
  assert.equal(whole[(12 * size + 20) * 4], 0, "the tie is ink on this side");
});

test("at any angle, a segment played out in random parts is the whole segment's raster", () => {
  // Painted as segments of their own between interpolated points, parts were
  // exact only in exact arithmetic: a split point a float's width off a
  // diagonal moved a pixel on the edge in about one segment in five hundred.
  // Seeded, so a failure reproduces.
  let seed = 7;
  const next = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const size = 64;
  const ink = [0, 0, 0, 255];
  for (let trial = 0; trial < 4000; trial += 1) {
    const a = { x: 16 + Math.floor(next() * 128) / 4, y: 16 + Math.floor(next() * 128) / 4 };
    const b = { x: 16 + Math.floor(next() * 128) / 4, y: 16 + Math.floor(next() * 128) / 4 };
    const radius = (1 + Math.floor(next() * 20)) / 2;
    const whole = new Uint8ClampedArray(size * size * 4).fill(255);
    rasterizePath(whole, size, size, [a, b], radius, ink, false);
    const parts = new Uint8ClampedArray(size * size * 4).fill(255);
    const play = createStrokePlayback({
      intervalMs: () => 100,
      paint: (_points, style, spans) => rasterizeSpans(parts, size, size, spans, style.radius, style.color),
    });
    play.enqueueSegments(a, [b], { radius, color: ink }, 0);
    for (let step = 0; step < 3; step += 1) play.advance(Math.floor(next() * 100));
    play.drain();
    assert.deepEqual(parts, whole, `trial ${trial}: ${JSON.stringify({ a, b, radius })}`);
  }
});

