/** A batch is played out over the interval that *produced* it.

Until #887 there was one interval, so a viewer could assume its own: every
drawer flushed at 80 ms and every viewer paced at 80 ms, matched by
construction. A cadence of its own for long-polling broke that, and nothing on
the wire says what the sender flushed at - so the server says it
(`drawerTransport` on `turn_started` and `sync_game`, R-DRAW-01) and the
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
import { useGameStore } from "../src/store/gameStore.ts";
import {
  applyClientConfig,
  flushIntervalFor,
  resetClientConfig,
} from "../src/lib/clientConfig.ts";

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

test("the drawing seat's transport resolves against whatever the cadences are now", () => {
  // The reason it is the transport on the wire and not the milliseconds. An
  // administrator can move either cadence while a turn is running, and every
  // client is told at once (`client_config`); a viewer holding the resolved
  // number went on pacing at the old one until the next turn began.
  resetClientConfig();
  assert.equal(flushIntervalFor("polling"), 240);
  assert.equal(flushIntervalFor("websocket"), 80);

  applyClientConfig({
    contractVersion: 5,
    flushIntervalMs: 120,
    pollingFlushIntervalMs: 360,
    drawingFramesPerWindow: 100,
    drawingWindowSeconds: 2,
    afkInputWindowMs: 60_000,
  });

  assert.equal(flushIntervalFor("polling"), 360, "the new cadence, mid-turn");
  assert.equal(flushIntervalFor("websocket"), 120);
  resetClientConfig();
});

test("anything but polling is the baseline, so nothing needs bounding", () => {
  // The value is an enum on the wire, not a number: a transport this build
  // has never heard of degrades exactly as a missing one does.
  resetClientConfig();
  for (const value of [null, undefined, "", "websocket", "webtransport", "POLLING", 240, {}]) {
    assert.equal(flushIntervalFor(value), 80, `${String(value)} should be the baseline`);
  }
});

test("the scratch pad never pays the polling cadence", async () => {
  // Its frames stay in the tab (#829), so a longer interval buys no bytes and
  // only delays the player's own ink off the preview layer.
  const { readFile } = await import("node:fs/promises");
  const pointer = await readFile(
    new URL("../src/hooks/useCanvasPointerInput.ts", import.meta.url), "utf8",
  );
  assert.match(
    pointer,
    /local\s*\n?\s*\?\s*config\.flushIntervalMs/,
    "the pad's own flush is the baseline, not its transport's",
  );
  const canvas = await readFile(new URL("../src/components/Canvas.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(canvas, /currentTransport/, "and neither is its playback");
});

/** What `Canvas.tsx` hands the renderer: the seat's transport as the last turn
named it, resolved against the cadences in force at the moment a batch is
scheduled. */
const drawerInterval = () => flushIntervalFor(useGameStore.getState().drawerTransport);

function aTurnDrawnOver(transport) {
  const store = useGameStore.getState();
  store.reset();
  store.startDrawing({
    drawerId: "p1", maskedPrompt: "_ _ _", roundNumber: 1, totalRounds: 3,
    seconds: 80, turnId: "t1", drawerTransport: transport,
  });
}

test("a cadence an administrator moves mid-turn reaches the viewer's pacing", () => {
  // The whole reason the transport is what travels. Before, the turn's payload
  // carried the resolved milliseconds, so a viewer went on pacing at the
  // cadence in force when the turn started - and `client_config` had already
  // told it the new one.
  resetClientConfig();
  aTurnDrawnOver("polling");
  assert.equal(drawerInterval(), 240);

  applyClientConfig({
    contractVersion: 5,
    flushIntervalMs: 80,
    pollingFlushIntervalMs: 360,
    drawingFramesPerWindow: 100,
    drawingWindowSeconds: 2,
    afkInputWindowMs: 60_000,
  });

  assert.equal(drawerInterval(), 360, "still the same turn, and no new payload");
  useGameStore.getState().reset();
  resetClientConfig();
});

test("a turn that names no transport paces at the baseline", () => {
  resetClientConfig();
  aTurnDrawnOver(undefined);
  assert.equal(useGameStore.getState().drawerTransport, null);
  assert.equal(drawerInterval(), 80);
  useGameStore.getState().reset();
});
