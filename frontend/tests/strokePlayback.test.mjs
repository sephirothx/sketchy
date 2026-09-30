import assert from "node:assert/strict";
import test from "node:test";

import { MAX_LAG_MS, createStrokePlayback } from "../src/lib/strokePlayback.ts";
import { rasterizePath, rasterizeSpans } from "../src/lib/canvasPixels.ts";
import { createCanvasSurface } from "../src/lib/canvasSurface.ts";
import { createProtocolRenderer } from "../src/lib/protocolRenderer.ts";

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

/** A drawer moving 1 px a millisecond from x = 0 at t = 0, a point every
10 ms, sending the start at once and the points at each flush of a timer
that runs free of the stroke - its first tick `phase` ms in, on the 10 ms
grid, since playback is uniform per segment rather than per pixel. Returns, for the
dot and for every stretch of ink painted, how long after it was drawn it
showed. */
function lagsOfAStroke(phase, interval = 80) {
  const shown = [];
  let now = 0;
  const play = createStrokePlayback({
    intervalMs: () => interval,
    paint: (points) => shown.push(now - points.at(-1).x),
  });
  play.enqueueStart(() => shown.push(now - 0), 0);
  let sent = 0;
  const flushes = [phase, phase + interval, phase + 2 * interval, phase + 3 * interval];
  for (now = 0; now <= 500; now += 1) {
    if (flushes.includes(now)) {
      const points = [];
      for (let x = sent + 10; x <= now; x += 10) points.push({ x, y: 0 });
      play.enqueueSegments({ x: sent, y: 0 }, points, STYLE, now);
      sent = now;
    }
    play.advance(now);
  }
  return shown;
}

test("a stroke's first point shows as far behind the hand as the rest of it (#1369)", () => {
  // The start is sent on pointer-down and the points that leave it at the
  // next flush, which are then played over the interval after that: a start
  // painted as it landed sat alone until they came.
  for (const phase of [10, 30, 70, 80]) {
    const lags = lagsOfAStroke(phase);
    assert.equal(lags[0], 80, `the dot, flush phase ${phase}`);
    // And no further behind than the dot: the first batch is played over the
    // time it took to follow the start, not a whole interval.
    for (const lag of lags) assert.ok(Math.abs(lag - 80) <= 1, `lag ${lag} at flush phase ${phase}`);
  }
});

test("a start behind unplayed ink waits for it, and an interval at least", () => {
  const { play, painted } = playback(80);
  const ran = [];
  play.enqueueSegments({ x: 0, y: 0 }, [{ x: 10, y: 0 }], STYLE, 0);
  play.enqueueStart(() => ran.push("start"), 10);
  assert.equal(play.advance(80), true, "the previous stroke has played; the start is due at 90");
  assert.deepEqual(ran, []);
  play.advance(90);
  assert.deepEqual(ran, ["start"]);

  const late = playback(80);
  late.play.enqueueSegments({ x: 0, y: 0 }, [{ x: 10, y: 0 }], STYLE, 0);
  late.play.enqueueStart(() => ran.push("second"), 0);
  late.play.advance(80);
  assert.deepEqual(ran, ["start", "second"], "due as the ink before it ends, which is an interval away");
  assert.equal(late.painted.length, 1);
});

test("a held start is run by a drain, and pulled in by the lag bound", () => {
  const { play } = playback(80);
  const ran = [];
  play.enqueueStart(() => ran.push("start"), 0);
  assert.equal(play.pending(), true);
  play.drain();
  assert.deepEqual(ran, ["start"]);

  const bounded = playback(80, 100);
  for (let batch = 0; batch < 3; batch += 1) {
    bounded.play.enqueueSegments({ x: batch * 10, y: 0 }, [{ x: batch * 10 + 10, y: 0 }], STYLE, 0);
  }
  bounded.play.enqueueStart(() => ran.push("pulled in"), 0);
  // 240 ms of ink ahead of it, and the bound is 100.
  assert.equal(bounded.play.advance(100), false);
  assert.deepEqual(ran, ["start", "pulled in"]);
});

test("the renderer holds a stroke's opening dot rather than painting it on arrival", () => {
  let clock = 0;
  const frames = [];
  const saved = { performance: globalThis.performance, window: globalThis.window };
  Object.defineProperty(globalThis, "performance", { value: { now: () => clock }, configurable: true });
  globalThis.window = {
    requestAnimationFrame: (callback) => frames.push(callback),
    cancelAnimationFrame: () => {},
  };
  try {
    let puts = 0;
    const surface = createCanvasSurface({
      createImageData: (width, height) => ({ width, height, data: new Uint8ClampedArray(width * height * 4) }),
      getImageData() { throw new Error("read"); },
      putImageData() { puts += 1; },
    });
    puts = 0;
    const renderer = createProtocolRenderer({ current: surface }, () => 80, null);
    renderer.apply({ event: "draw_start", payload: { x: 0.1, y: 0.1, color: "#000000", width: 8 } });
    assert.equal(puts, 0, "painted on arrival");
    clock = 79;
    frames.shift()();
    assert.equal(frames.length, 1, "still waiting for it");
    assert.equal(puts, 0, "painted before the interval was up");
    renderer.apply({ event: "draw_move", payload: { points: [{ x: 0.2, y: 0.1 }], widths: null, ends: false } });
    clock = 80;
    frames.shift()();
    assert.ok(puts > 0, "the dot shows once its interval is up");
    renderer.dispose();
  } finally {
    Object.defineProperty(globalThis, "performance", { value: saved.performance, configurable: true });
    globalThis.window = saved.window;
  }
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

