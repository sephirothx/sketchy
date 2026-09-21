import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  MAX_HEALTH_COUNT,
  MAX_JOIN_TO_DRAWING_MS,
  MAX_JOIN_TO_DRAWING_READINGS,
  createHealthLedger,
} from "../src/lib/connectionHealth.ts";
import { createStrokePlayback } from "../src/lib/strokePlayback.ts";
import { createProtocolRenderer } from "../src/lib/protocolRenderer.ts";
import { createCanvasSurface } from "../src/lib/canvasSurface.ts";

// What only the client can see about its connection (#876, R-OBS-20), sent at
// most once a minute and only when something happened.

test("a session where nothing happened sends nothing at all", () => {
  // Every one of these is rare in normal play; a report of zeros would be
  // four hundred messages a minute at the scale target saying nothing.
  const ledger = createHealthLedger();
  assert.equal(ledger.take(), null);
});

test("a report carries the counts since the last one, and taking it clears them", () => {
  const ledger = createHealthLedger();
  ledger.note("droppedEmits");
  ledger.note("droppedEmits");
  ledger.note("stallFallbacks");
  ledger.noteJoinToDrawing(812.6);

  assert.deepEqual(ledger.take(), {
    tailRejected: 0,
    syncExhausted: 0,
    droppedEmits: 2,
    stallFallbacks: 1,
    playbackCompressions: 0,
    joinToDrawingMs: [813],
  });
  assert.equal(ledger.take(), null, "the next minute starts from nothing");
});

test("a report is held to the bounds the server enforces", () => {
  // Mirrors `payloads.py`: a report the server would refuse is one lost whole.
  const ledger = createHealthLedger();
  for (let i = 0; i < MAX_HEALTH_COUNT + 50; i += 1) ledger.note("playbackCompressions");
  for (let i = 0; i < MAX_JOIN_TO_DRAWING_READINGS + 3; i += 1) ledger.noteJoinToDrawing(100);
  ledger.noteJoinToDrawing(Number.NaN);

  const report = ledger.take();
  assert.equal(report.playbackCompressions, MAX_HEALTH_COUNT);
  assert.equal(report.joinToDrawingMs.length, MAX_JOIN_TO_DRAWING_READINGS);

  ledger.noteJoinToDrawing(MAX_JOIN_TO_DRAWING_MS * 3);
  ledger.noteJoinToDrawing(-40);
  assert.deepEqual(ledger.take().joinToDrawingMs, [MAX_JOIN_TO_DRAWING_MS, 0]);
});

test("a report that could not be sent goes with the next one", () => {
  const ledger = createHealthLedger();
  ledger.note("tailRejected");
  const unsent = ledger.take();
  ledger.note("tailRejected");
  ledger.restore(unsent);
  assert.equal(ledger.take().tailRejected, 2);
});

test("a report names nothing but its counts", () => {
  // No identifier, no content, no free text: the whole payload is these keys,
  // and every value a number the server bounds.
  const ledger = createHealthLedger();
  ledger.note("syncExhausted");
  ledger.noteJoinToDrawing(5);
  const report = ledger.take();
  assert.deepEqual(Object.keys(report).sort(), [
    "droppedEmits", "joinToDrawingMs", "playbackCompressions",
    "stallFallbacks", "syncExhausted", "tailRejected",
  ]);
  for (const [key, value] of Object.entries(report)) {
    if (key === "joinToDrawingMs") assert.ok(value.every(Number.isInteger));
    else assert.ok(Number.isInteger(value), key);
  }
});

test("playback says when it compresses a schedule that fell behind, and only then", () => {
  const style = { radius: 2, color: [0, 0, 0, 255] };
  let compressions = 0;
  const play = createStrokePlayback({
    intervalMs: () => 80,
    paint: () => {},
    onCompress: () => { compressions += 1; },
  });
  // Batches arriving at the interval that produced them: never behind.
  play.enqueueSegments({ x: 0, y: 0 }, [{ x: 1, y: 0 }], style, 0);
  play.advance(80);
  play.enqueueSegments({ x: 1, y: 0 }, [{ x: 2, y: 0 }], style, 80);
  assert.equal(compressions, 0);
  // A burst: five batches at once is 400 ms queued, past the 250 ms bound.
  for (let i = 0; i < 5; i += 1) play.enqueueSegments({ x: i, y: 1 }, [{ x: i + 1, y: 1 }], style, 100);
  assert.ok(compressions > 0, "a burst past the lag bound is a compression");
});

function surface() {
  return createCanvasSurface({
    createImageData: (width, height) => ({ width, height, data: new Uint8ClampedArray(width * height * 4) }),
    getImageData() { throw new Error("read"); },
    putImageData() {},
  });
}

function burst(renderer) {
  renderer.apply({ event: "draw_start", payload: { x: 0.1, y: 0.1, color: "#000000", width: 4 } });
  for (let i = 0; i < 6; i += 1) {
    renderer.apply({
      event: "draw_move",
      payload: { points: [{ x: 0.1 + i * 0.01, y: 0.2 }], widths: null, ends: false },
    });
  }
}

test("a hidden tab's growing queue is not counted as lag", () => {
  // A hidden tab gets no animation frames, so every batch that lands finds
  // the schedule behind: counting those would measure hidden tabs.
  globalThis.window ??= { requestAnimationFrame: () => 1, cancelAnimationFrame: () => {} };
  const previous = globalThis.document;
  let counted = 0;
  try {
    globalThis.document = { visibilityState: "hidden" };
    const hidden = createProtocolRenderer({ current: surface() }, () => 80, null, () => { counted += 1; });
    burst(hidden);
    assert.equal(counted, 0, "hidden: nothing counted");
    hidden.dispose();

    globalThis.document = { visibilityState: "visible" };
    const shown = createProtocolRenderer({ current: surface() }, () => 80, null, () => { counted += 1; });
    burst(shown);
    assert.ok(counted > 0, "visible: the same burst is counted");
    shown.dispose();
  } finally {
    globalThis.document = previous;
  }
});

test("the pad reports no compressions, and the ledger has no socket in it", () => {
  // The pad's frames never crossed a network; and `connectionHealth.ts` must
  // stay loadable without `io()` so the renderer can import it.
  const canvas = readFileSync(new URL("../src/components/Canvas.tsx", import.meta.url), "utf8");
  assert.match(canvas, /local \? undefined : \(\) => noteHealth\("playbackCompressions"\)/);
  const ledger = readFileSync(new URL("../src/lib/connectionHealth.ts", import.meta.url), "utf8");
  assert.doesNotMatch(ledger, /from "\.\/socket/);
});
