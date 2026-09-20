/** A batch is played out over the interval that *produced* it.

Until #887 there was one interval, so a viewer could assume its own: every
drawer flushed at 80 ms and every viewer paced at 80 ms, matched by
construction. A cadence of its own for long-polling broke that, and nothing on
the wire says what the sender flushed at - so the server says it
(`drawerFlushIntervalMs` on `turn_started` and `sync_game`, R-DRAW-01) and the
renderer takes it as an argument.

Both mismatches are failures, in opposite directions: pacing a 240 ms batch
over 80 leaves the canvas still for the remaining 160 (the stepping #559
removed), and pacing an 80 ms batch over 240 falls past `MAX_LAG_MS` on the
next batch and is compressed into a crawl and a snap.
*/
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import { createStrokePlayback } from "../src/lib/strokePlayback.ts";
import { createProtocolRenderer } from "../src/lib/protocolRenderer.ts";
import { createCanvasSurface } from "../src/lib/canvasSurface.ts";

const STYLE = { radius: 2, color: [0, 0, 0, 255] };
const FRAME_MS = 16;

/** Play `batches` arriving every `senderMs`, painting at a screen's rate, and
count the frames that advanced the ink. */
function frames({ senderMs, playbackMs, batches = 5, points = 8 }) {
  let painted = 0;
  const play = createStrokePlayback({
    intervalMs: () => playbackMs,
    paint: () => { painted += 1; },
  });
  let advanced = 0;
  let total = 0;
  let from = { x: 0, y: 0 };
  for (let batch = 0; batch < batches; batch += 1) {
    const arrival = batch * senderMs;
    const polyline = [];
    for (let i = 1; i <= points; i += 1) polyline.push({ x: (batch * points + i) * 2, y: 0 });
    play.enqueueSegments(from, polyline, STYLE, arrival);
    from = polyline[polyline.length - 1];
    for (let now = arrival; now < arrival + senderMs; now += FRAME_MS) {
      const before = painted;
      play.advance(now);
      total += 1;
      if (painted > before) advanced += 1;
    }
  }
  return advanced / total;
}

test("a viewer paced at the sender's cadence keeps the ink moving", () => {
  assert.ok(frames({ senderMs: 80, playbackMs: 80 }) > 0.9);
  assert.ok(frames({ senderMs: 240, playbackMs: 240 }) > 0.9);
});

test("a viewer paced faster than the sender freezes between batches", () => {
  // The drawer on long-polling, every viewer at the WebSocket baseline: ink
  // for 80 ms of each 240, then nothing. This is what the field prevents.
  const moving = frames({ senderMs: 240, playbackMs: 80 });
  assert.ok(moving < 0.5, `${moving} of frames advanced; expected the canvas to sit still`);
});

test("a viewer paced slower than the sender is compressed by the lag bound", () => {
  // The other direction: scheduling an 80 ms batch over 240 puts the queue
  // past MAX_LAG_MS, and every batch arrives to a schedule being yanked.
  const moving = frames({ senderMs: 80, playbackMs: 240 });
  assert.ok(moving < 0.9, `${moving} of frames advanced smoothly; expected compression`);
});

/** A drawing surface over a write-only 2D context, as `Canvas.tsx` builds one. */
function surface() {
  const context = {
    createImageData: (width, height) => ({
      width, height, data: new Uint8ClampedArray(width * height * 4),
    }),
    getImageData() { throw new Error("the drawing canvas was read"); },
    putImageData() {},
  };
  return createCanvasSurface(context);
}

test("the renderer plays at the interval it is given, not one it looks up", () => {
  // The renderer drives playback off animation frames; nothing here needs one
  // to run, only for scheduling not to throw.
  globalThis.window ??= { requestAnimationFrame: () => 1, cancelAnimationFrame: () => {} };
  // The regression that shipped: the interval came from this client's own
  // config, so a WebSocket viewer paced a polling drawer's batch at 80 ms.
  // Injected, the renderer has no opinion - and no import of the socket.
  const asked = [];
  const renderer = createProtocolRenderer({ current: surface() }, () => {
    asked.push(true);
    return 240;
  }, null);
  renderer.apply({
    event: "draw_start",
    payload: { x: 0, y: 0, color: "#000000", width: 4 },
  });
  renderer.apply({
    event: "draw_move",
    payload: {
      points: [{ x: 100, y: 100 }, { x: 200, y: 100 }],
      widths: null,
      ends: false,
    },
  });
  assert.ok(asked.length > 0, "playback never asked for the sender's interval");
  renderer.dispose();
});

test("the renderer's module graph has no socket in it", () => {
  // `strokePlayback` is documented pure ("`now` and the interval are
  // injected"); reading the interval here pulled `io()` in behind it.
  const source = readFileSync(
    new URL("../src/lib/protocolRenderer.ts", import.meta.url),
    "utf8",
  );
  assert.ok(!/from "\.\/socket/.test(source), "the renderer imports the socket singleton");
  assert.ok(!/clientConfig/.test(source), "the renderer reads a cadence of its own");
});
