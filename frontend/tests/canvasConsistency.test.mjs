/* One picture on every screen (R-DRAW-14, R-DRAW-16).

A drawing reaches a pixel buffer by five routes: the drawer's own ink, a
viewer's live playback, a late joiner's replay followed by live playback, the
replay a gallery plays out over time, and a scrub. #940 and #950 were each two
of those routes disagreeing about one pixel, found by accident in a benchmark;
a fill after such a pixel can flood a region on one screen and not another.

This drives random sessions - mouse and pen strokes, shapes, fills, clears -
through every route and requires identical pixels. The rasterizers, the wire
codec, the client history, the playback queue and the replay stepper are the
real modules; the glue that calls them from the pointer hook
(`useCanvasPointerInput.ts`) and the protocol renderer (`Canvas.tsx`) is
mirrored here, step for step, so a change there has to change this too. */

import assert from "node:assert/strict";
import test from "node:test";

import {
  CANVAS_HEIGHT as H,
  CANVAS_WIDTH as W,
  ClientCanvasHistory,
  decodeCanvasHistory,
} from "../src/lib/canvasHistory.ts";
import { toPixels } from "../src/lib/canvasGeometry.ts";
import {
  applyCanvasAction,
  applyCanvasStrokeSpan,
  applyFillAction,
  drawShapeOutlinePixels,
  fillWhite,
  rasterizePath,
  rasterizePolyline,
  rasterizeSegmentSpans,
  renderCanvasActions,
  renderCanvasActionsUpTo,
} from "../src/lib/canvasRenderer.ts";
import { hexToRgba } from "../src/lib/canvasPixels.ts";
import { createCanvasSurface } from "../src/lib/canvasSurface.ts";
import {
  decodeLiveDrawing,
  encodeClear,
  encodeFill,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
  encodeShape,
} from "../src/lib/liveDrawing.ts";
import { finalWidth, rampedBatch } from "../src/lib/pathWidths.ts";
import { PenStroke } from "../src/lib/penStroke.ts";
import { createPointThinner } from "../src/lib/pointThinning.ts";
import { replayPlan, stepReplay } from "../src/lib/replay.ts";
import { createStrokePlayback } from "../src/lib/strokePlayback.ts";

const COLORS = ["#000000", "#e03131", "#1971c2", "#2f9e44", "#ffffff"];
const SHAPES = ["rectangle", "ellipse", "triangle"];
const FLUSH_MS = 80;

/** A drawing canvas as `Canvas.tsx` makes one: a surface over a 2D context.
The context only takes writes - a read throws - so a painter that went back
to reading the canvas fails here (`canvasSurface.ts`). What it shows is kept
apart from the surface's pixels, and checked against them at the end. */
function fakeContext() {
  const screen = new Uint8ClampedArray(W * H * 4);
  const context = {
    createImageData(width, height) {
      return { width, height, data: new Uint8ClampedArray(width * height * 4) };
    },
    getImageData() {
      throw new Error("the drawing canvas was read");
    },
    putImageData(image, x, y, dirtyX = 0, dirtyY = 0, dirtyWidth = image.width, dirtyHeight = image.height) {
      for (let row = dirtyY; row < dirtyY + dirtyHeight; row++) {
        const from = (row * image.width + dirtyX) * 4;
        screen.set(image.data.subarray(from, from + dirtyWidth * 4), ((y + row) * W + x + dirtyX) * 4);
      }
    },
  };
  const surface = createCanvasSurface(context);
  surface.screen = screen;
  return surface;
}

function random(seed) {
  let state = seed;
  const next = () => ((state = (state * 1103515245 + 12345) % 2147483648) / 2147483648);
  return {
    next,
    int: (low, high) => low + Math.floor(next() * (high - low + 1)),
    pick: (list) => list[Math.floor(next() * list.length)],
  };
}

/** A normalized point on the wire's quarter-pixel grid, as `normalizedPoint` makes one. */
function gridPoint(x, y) {
  const clamp = (value, size) => Math.max(0, Math.min(size * 4, Math.round(value * 4)));
  return { x: clamp(x, W) / (W * 4), y: clamp(y, H) / (H * 4) };
}

/** Pointer samples for one stroke: steps of every size the probes used,
turns, reversals, and pauses that repeat a sample. */
function strokeSamples(rng) {
  let x = rng.int(0, W * 4) / 4;
  let y = rng.int(0, H * 4) / 4;
  const step = rng.pick([0.25, 1, 1.7, 3.4, 7, 20]);
  let heading = rng.next() * 2 * Math.PI;
  const samples = [gridPoint(x, y)];
  const count = rng.int(1, 40);
  for (let index = 0; index < count; index++) {
    if (rng.next() < 0.3) heading += (rng.next() - 0.5) * 3;
    if (rng.next() < 0.05) heading += Math.PI;
    if (rng.next() > 0.08) {
      x += step * Math.cos(heading) + (rng.next() - 0.5);
      y += step * Math.sin(heading) + (rng.next() - 0.5);
    }
    samples.push(gridPoint(x, y));
  }
  return samples;
}

/** The drawer: paints its own canvas as `useCanvasPointerInput` does, and
returns the frames it sent, in order. */
function drawSession(rng, gestures) {
  const canvas = fakeContext();
  const frames = [];
  for (let gesture = 0; gesture < gestures; gesture++) {
    const roll = rng.next();
    const color = rng.pick(COLORS);
    const width = rng.pick([1, 2, 3, 4, 5, 6, 8, 11, 16, 24, 33, 64]);
    const rgba = hexToRgba(color);
    const paintRuns = (runs) => {
      for (const run of runs) rasterizePath(canvas, run.points, run.width / 2, rgba, false);
    };
    if (roll < 0.6) {
      const samples = strokeSamples(rng);
      const start = samples[0];
      const pen = rng.next() < 0.4;
      const startWidth = pen ? Math.max(1, width - rng.int(0, 4)) : width;
      const penStroke = pen ? new PenStroke(toPixels(start), startWidth) : null;
      let target = startWidth;
      const thinner = createPointThinner(start);
      let last = start;
      let lastSent = start;
      let pending = [];
      rasterizePath(canvas, [toPixels(start), toPixels(start)], startWidth / 2, rgba, false);
      frames.push(encodePathStart({ x: start.x, y: start.y, color, width: startWidth }));

      const accept = (points) => {
        for (const point of points) {
          if (penStroke) {
            // A keyframe rides a kept point (R-DRAW-16).
            const key = rng.next() < 0.35 ? target : undefined;
            paintRuns(penStroke.accept(toPixels(point), key).runs);
          } else {
            paintRuns([{ points: [toPixels(last), toPixels(point)], width }]);
          }
          last = point;
          pending.push({ x: point.x, y: point.y });
        }
      };
      const flushPen = () => {
        if (penStroke) paintRuns(penStroke.flush(target).runs);
      };
      const send = (ends = false) => {
        if (pending.length === 0) return false;
        const widths = penStroke?.takeFrame() ?? [];
        frames.push(encodePathPoints({
          points: pending,
          previous: lastSent,
          ...(widths.length > 0 ? { widths } : {}),
          ...(ends ? { ends: true } : {}),
        }));
        penStroke?.frameSent();
        lastSent = pending.at(-1);
        pending = [];
        return true;
      };

      for (const sample of samples.slice(1)) {
        if (penStroke && rng.next() < 0.5) {
          target = Math.max(1, Math.min(64, target + rng.int(-3, 3)));
        }
        accept(thinner.push(sample));
        if (rng.next() < 0.25) {
          // The flush timer: the pending sample goes with the frame.
          accept(thinner.flush());
          flushPen();
          send();
        }
      }
      accept(thinner.end());
      flushPen();
      if (!send(true)) frames.push(encodePathEnd());
    } else if (roll < 0.8) {
      const from = gridPoint(rng.int(-40, W + 40), rng.int(-40, H + 40));
      const to = gridPoint(rng.int(0, W * 4) / 4, rng.int(0, H * 4) / 4);
      const shape = rng.pick(SHAPES);
      drawShapeOutlinePixels(canvas, from, to, shape, color, width);
      frames.push(encodeShape({ shape, from, to, color, width }));
    } else if (roll < 0.97) {
      const payload = { ...gridPoint(rng.int(0, W * 4 - 1) / 4, rng.int(0, H * 4 - 1) / 4), color };
      if (applyFillAction(canvas, payload)) frames.push(encodeFill(payload));
    } else {
      fillWhite(canvas);
      frames.push(encodeClear());
    }
  }
  return { pixels: canvas.pixels, canvas, frames };
}

/** A viewer's canvas, as `Canvas.tsx`'s protocol renderer paints it, fed as
`useCanvasProtocol` feeds it: each frame decoded against the history, applied
to it, then handed to the renderer. Time moves on a fake clock, with animation
frames landing at random, so strokes are painted in arbitrary parts. */
function createViewer(rng) {
  const canvas = fakeContext();
  const history = new ClientCanvasHistory();
  history.reset([0, 1, 0, 0]);
  const queued = { last: null, color: "#000000", width: 4 };
  const playback = createStrokePlayback({
    intervalMs: () => FLUSH_MS,
    paint: (_points, style, spans) => rasterizeSegmentSpans(canvas, spans, style.radius, style.color),
  });
  let now = 0;

  const apply = (packet) => {
    if (packet.event === "draw_start") {
      const { x, y, color, width } = packet.payload;
      const point = toPixels({ x, y });
      queued.last = point;
      queued.color = color;
      queued.width = width;
      playback.enqueueBarrier(() => rasterizePolyline(canvas, [point, point], width / 2, hexToRgba(color)), now);
    } else if (packet.event === "draw_move") {
      if (packet.payload.points.length === 0 || !queued.last) return;
      const style = { radius: queued.width / 2, color: hexToRgba(queued.color) };
      const points = packet.payload.points.map(toPixels);
      const batch = rampedBatch(queued.last, points, queued.width, packet.payload.widths);
      playback.enqueueSegments(queued.last, batch.points, style, now, batch.segmentWidths.map((width) => width / 2));
      queued.width = batch.finalWidth;
      queued.last = packet.payload.ends ? null : points.at(-1);
    } else if (packet.event === "draw_end") {
      queued.last = null;
    } else if (packet.event === "draw_shape") {
      const { from, to, shape, color, width } = packet.payload;
      playback.enqueueBarrier(() => drawShapeOutlinePixels(canvas, from, to, shape, color, width), now);
    } else if (packet.event === "draw_fill") {
      const payload = packet.payload;
      playback.enqueueBarrier(() => applyFillAction(canvas, payload), now);
    } else if (packet.event === "clear_canvas") {
      playback.cancel();
      fillWhite(canvas);
      queued.last = null;
    }
  };

  return {
    canvas,
    history,
    receive(frame) {
      const packet = decodeLiveDrawing(frame, history.openPathLastPoint());
      assert.ok(packet && packet.event !== "draw_move_relative", "a frame decodes against the history");
      history.apply(packet);
      apply(packet);
      // Animation frames until the next frame arrives.
      const until = now + rng.int(0, 120);
      while (now < until) {
        now = Math.min(until, now + rng.int(1, 40));
        playback.advance(now);
      }
    },
    /** `replay` in `Canvas.tsx`: the history repainted, and a path it ends
    on left open for the live batches that follow. */
    replay(actions) {
      playback.cancel();
      renderCanvasActions(canvas, actions);
      const last = actions.at(-1);
      const end = last?.kind === "path" ? last.points.at(-1) : undefined;
      if (last?.kind === "path" && end) {
        queued.last = { x: end.x, y: end.y };
        queued.color = last.color;
        queued.width = finalWidth(last.width, last.widths);
      } else {
        queued.last = null;
      }
    },
    drain() { playback.drain(); },
  };
}

/** The server's `sync_strokes` history: the `SKCH` envelope around the same
records the history hash is taken over (`backend/app/canvas_history.py`). */
function encodeSkch(actions) {
  const records = actions.map((action) => {
    if (action.kind === "path") {
      const widths = action.widths ?? [];
      const bytes = new Uint8Array(5 + (action.points.length + widths.length) * 4);
      const view = new DataView(bytes.buffer);
      const color = parseInt(action.color.slice(1), 16);
      bytes.set([0, color >> 16, (color >> 8) & 0xff, color & 0xff, action.width]);
      let offset = 5;
      let next = 0;
      action.points.forEach((point, index) => {
        if (next < widths.length && widths[next][0] === index) {
          view.setInt16(offset, -32768, true);
          view.setInt16(offset + 2, widths[next][1], true);
          offset += 4;
          next += 1;
        }
        view.setInt16(offset, Math.round(point.x * 4), true);
        view.setInt16(offset + 2, Math.round(point.y * 4), true);
        offset += 4;
      });
      return bytes;
    }
    if (action.kind === "shape") {
      const { shape, color, width, from, to } = action.payload;
      const bytes = new Uint8Array(14);
      const view = new DataView(bytes.buffer);
      const rgb = parseInt(color.slice(1), 16);
      bytes.set([1, SHAPES.indexOf(shape), rgb >> 16, (rgb >> 8) & 0xff, rgb & 0xff, width]);
      view.setInt16(6, Math.round(from.x * W * 4), true);
      view.setInt16(8, Math.round(from.y * H * 4), true);
      view.setInt16(10, Math.round(to.x * W * 4), true);
      view.setInt16(12, Math.round(to.y * H * 4), true);
      return bytes;
    }
    if (action.kind === "fill") {
      const bytes = new Uint8Array(8);
      const view = new DataView(bytes.buffer);
      const rgb = parseInt(action.color.slice(1), 16);
      bytes.set([2, rgb >> 16, (rgb >> 8) & 0xff, rgb & 0xff]);
      view.setUint16(4, action.x, true);
      view.setUint16(6, action.y, true);
      return bytes;
    }
    return Uint8Array.of(3);
  });
  const dataLength = records.reduce((sum, record) => sum + record.length, 0);
  const headerLength = 7 + (records.length + 1) * 4;
  const bytes = new Uint8Array(headerLength + dataLength);
  const view = new DataView(bytes.buffer);
  bytes.set([0x53, 0x4b, 0x43, 0x48, 1]);
  view.setUint16(5, records.length, true);
  let offset = 0;
  records.forEach((record, index) => {
    view.setUint32(7 + index * 4, offset, true);
    bytes.set(record, headerLength + offset);
    offset += record.length;
  });
  view.setUint32(7 + records.length * 4, offset, true);
  return bytes;
}

/** The gallery's replay, played out in random steps from a random scrub. */
function playedReplay(rng, actions) {
  const pixels = new Uint8ClampedArray(W * H * 4);
  const plan = replayPlan(actions);
  let position = plan.positionAt(rng.next());
  renderCanvasActionsUpTo(pixels, actions, position);
  while (position.action < actions.length) {
    const stepped = stepReplay(actions, plan, position, rng.next() * 40, {
      span: (stroke, from, to) => applyCanvasStrokeSpan(pixels, stroke, from, to),
      whole: (action) => applyCanvasAction(pixels, action),
    });
    position = stepped.position;
  }
  return pixels;
}

function firstDifference(a, b) {
  for (let index = 0; index < a.length; index += 4) {
    if (a[index] !== b[index] || a[index + 1] !== b[index + 1] || a[index + 2] !== b[index + 2]) {
      const pixel = index / 4;
      return `pixel (${pixel % W}, ${Math.floor(pixel / W)})`;
    }
  }
  return null;
}

test("every route to a canvas paints the drawer's pixels", () => {
  for (let session = 0; session < 60; session++) {
    const rng = random(9500 + session);
    const drawer = drawSession(rng, rng.int(4, 18));

    const viewer = createViewer(rng);
    // A late joiner arrives at a random frame, mid-stroke as often as not:
    // the history the server holds then, and live frames after it.
    const joinAt = rng.int(0, drawer.frames.length);
    const joiner = createViewer(rng);
    drawer.frames.forEach((frame, index) => {
      if (index === joinAt) {
        const actions = decodeCanvasHistory(encodeSkch(viewer.history.actions));
        assert.ok(actions, "the history decodes");
        joiner.history.actions = actions;
        joiner.replay(actions);
      }
      viewer.receive(frame);
      if (index >= joinAt) joiner.receive(frame);
    });
    if (joinAt === drawer.frames.length) {
      const actions = decodeCanvasHistory(encodeSkch(viewer.history.actions));
      joiner.history.actions = actions;
      joiner.replay(actions);
    }
    viewer.drain();
    joiner.drain();

    const actions = decodeCanvasHistory(encodeSkch(viewer.history.actions));
    const replayed = fakeContext();
    renderCanvasActions(replayed, actions);

    const routes = {
      "live viewer": viewer.canvas.pixels,
      "late joiner": joiner.canvas.pixels,
      "whole replay": replayed.pixels,
      "played replay": playedReplay(rng, actions),
    };
    // What each live canvas shows is what it holds: every change was committed.
    for (const [route, canvas] of [["drawer", drawer.canvas], ["live viewer", viewer.canvas], ["late joiner", joiner.canvas]]) {
      assert.equal(firstDifference(canvas.pixels, canvas.screen), null, `session ${session}: the ${route}'s screen lags its pixels`);
    }
    for (const [route, pixels] of Object.entries(routes)) {
      const difference = firstDifference(drawer.pixels, pixels);
      assert.equal(difference, null, `session ${session}: the ${route} differs from the drawer at ${difference}`);
    }
  }
});
