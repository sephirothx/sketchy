import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeLiveDrawing,
  encodeClear,
  encodeFill,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
  encodeShape,
} from "../src/lib/liveDrawing.ts";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "../src/lib/canvasHistory.ts";

test("live drawing frames round-trip with compact fixed sizes", () => {
  const cases = [
    [encodePathStart({ x: 0.25, y: 0.75, color: "#aabbcc", width: 4 }), "draw_start", 9],
    // A whole canvas apart, so delta coding would need an escape and come out
    // larger; the encoder falls back to absolute.
    [encodePathPoints({ points: [{ x: 0.1, y: 0.2 }, { x: 1.2, y: -0.1 }] }), "draw_move", 9],
    // Adjacent pointer samples: two bytes per point after the first, which is
    // the case that carries essentially all of the traffic.
    [encodePathPoints({
      points: [{ x: 0.1, y: 0.2 }, { x: 0.105, y: 0.205 }, { x: 0.11, y: 0.21 }],
    }), "draw_move", 9],
    [encodePathEnd(), "draw_end", null],
    [encodeShape({
      shape: "ellipse",
      from: { x: 0.1, y: 0.2 },
      to: { x: 0.8, y: 0.9 },
      color: "#123456",
      width: 64,
    }), "draw_shape", 14],
    [encodeFill({ x: 0.25, y: 0.75, color: "#fedcba" }), "draw_fill", 8],
    [encodeClear(), "clear_canvas", null],
  ];

  for (const [frame, event, size] of cases) {
    if (size === null) assert.equal(typeof frame, "number");
    else assert.equal(frame.byteLength, size);
    assert.equal(decodeLiveDrawing(frame)?.event, event);
  }
});

test("decoder accepts ArrayBuffer and rejects malformed frames", () => {
  const frame = encodePathStart({ x: 0.5, y: 0.5, color: "#000000", width: 4 });
  assert.equal(decodeLiveDrawing(frame.buffer)?.event, "draw_start");
  assert.equal(decodeLiveDrawing(new Uint8Array()), null);
  assert.equal(decodeLiveDrawing(Uint8Array.of(0x20)), null);
  assert.equal(decodeLiveDrawing(Uint8Array.of(0x11)), null);
  assert.equal(decodeLiveDrawing(Uint8Array.of(0x15, 0)), null);
  assert.equal(decodeLiveDrawing(0x10), null);
  assert.equal(decodeLiveDrawing(0x22), null);
});

test("fill coordinates preserve the addressed canvas pixel", () => {
  // The property the name promises, rather than the arithmetic that used to
  // implement it. A seed point crosses the wire as an integer pixel and is
  // re-quantized by the renderer, and `x / CANVAS_WIDTH` did not survive that
  // for 37 of the 800 columns - those fills started a pixel to the left. For a
  // flood fill one pixel can be the far side of an outline, so the wrong
  // region gets painted entirely.
  for (let x = 0; x < CANVAS_WIDTH; x += 1) {
    const packet = decodeLiveDrawing(
      encodeFill({ x: (x + 0.5) / CANVAS_WIDTH, y: 0.5, color: "#abcdef" }),
    );
    const rendered = Math.floor(packet.payload.x * CANVAS_WIDTH);
    assert.equal(rendered, x, `fill at x=${x} rendered at ${rendered}`);
  }
  for (let y = 0; y < CANVAS_HEIGHT; y += 1) {
    const packet = decodeLiveDrawing(
      encodeFill({ x: 0.5, y: (y + 0.5) / CANVAS_HEIGHT, color: "#abcdef" }),
    );
    const rendered = Math.floor(packet.payload.y * CANVAS_HEIGHT);
    assert.equal(rendered, y, `fill at y=${y} rendered at ${rendered}`);
  }
  // The last pixel still clamps rather than running off the canvas.
  const edge = decodeLiveDrawing(encodeFill({ x: 0.9999, y: 0.9999, color: "#abcdef" }));
  assert.equal(Math.floor(edge.payload.x * CANVAS_WIDTH), CANVAS_WIDTH - 1);
  assert.equal(Math.floor(edge.payload.y * CANVAS_HEIGHT), CANVAS_HEIGHT - 1);
});
