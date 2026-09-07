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
  endsPath,
  resolveRelativePoints,
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

test("a relative frame is offsets from the open path and three bytes a point (#559)", () => {
  const previous = { x: 0.5, y: 0.5 };
  const one = encodePathPoints({ points: [{ x: 0.5, y: 0.51 }], previous });
  assert.equal(one.byteLength, 3);
  assert.equal(one[0] & 0x0f, 7);
  // Without the predecessor: offsets, for the caller to resolve.
  const unresolved = decodeLiveDrawing(one);
  assert.equal(unresolved.event, "draw_move_relative");
  assert.deepEqual(unresolved.payload.records, [{ dx: 0, dy: 24 }]);
  // With it: points.
  const resolved = decodeLiveDrawing(one, previous);
  assert.equal(resolved.event, "draw_move");
  assert.deepEqual(resolved.payload.points, [{ x: 0.5, y: 0.51 }]);
  assert.deepEqual(resolveRelativePoints(unresolved, { x: 0.25, y: 0.25 }).payload.points, [{ x: 0.25, y: 0.26 }]);

  const many = encodePathPoints({ points: [{ x: 0.5, y: 0.51 }, { x: 0.51, y: 0.52 }, { x: 0.52, y: 0.52 }], previous });
  assert.equal(many.byteLength, 1 + 3 * 2);
  assert.deepEqual(decodeLiveDrawing(many, previous).payload.points, [{ x: 0.5, y: 0.51 }, { x: 0.51, y: 0.52 }, { x: 0.52, y: 0.52 }]);

  // A first step too far falls back to a self-contained frame; a later jump
  // escapes to an absolute pair inside the relative frame.
  const far = encodePathPoints({ points: [{ x: 0.9, y: 0.9 }], previous });
  assert.notEqual(far[0] & 0x0f, 7);
  assert.equal(far.byteLength, 5);
  const jump = encodePathPoints({ points: [{ x: 0.5, y: 0.51 }, { x: 0.9, y: 0.9 }], previous });
  assert.equal(jump[0] & 0x0f, 7);
  assert.equal(jump.byteLength, 1 + 2 + 5);
  assert.deepEqual(decodeLiveDrawing(jump, previous).payload.points[1], { x: 0.9, y: 0.9 });

  // Malformed: no records, half a record, an escape with half a pair.
  for (const bytes of [[0x17], [0x17, 1], [0x17, 0x80, 0, 0]]) {
    assert.equal(decodeLiveDrawing(new Uint8Array(bytes), previous), null);
  }
  // A walk off the packed range resolves to nothing.
  const walk = new Uint8Array(1 + 256 * 2);
  walk[0] = 0x17;
  for (let i = 1; i < walk.length; i += 2) walk[i] = 127;
  assert.equal(decodeLiveDrawing(walk, { x: 1, y: 0.5 }), null);
});

test("a final batch is the relative layout under its own tag and closes the path (#603)", () => {
  const previous = { x: 0.5, y: 0.5 };
  const final = encodePathPoints({ points: [{ x: 0.5, y: 0.51 }], previous, ends: true });
  assert.equal(final.byteLength, 3);
  assert.equal(final[0] & 0x0f, 8);
  const unresolved = decodeLiveDrawing(final);
  assert.equal(unresolved.event, "draw_move_relative");
  assert.equal(unresolved.payload.ends, true);
  assert.equal(endsPath(unresolved), true);
  const resolved = decodeLiveDrawing(final, previous);
  assert.deepEqual(resolved, { event: "draw_move", payload: { points: [{ x: 0.5, y: 0.51 }], ends: true } });
  assert.equal(endsPath(resolved), true);
  assert.equal(endsPath(decodeLiveDrawing(encodePathPoints({ points: [{ x: 0.5, y: 0.51 }], previous }), previous)), false);
  assert.equal(endsPath(decodeLiveDrawing(encodePathEnd())), true);
  // Too far for a byte: escapes rather than falling back to a form that
  // could not carry the end.
  const far = encodePathPoints({ points: [{ x: 0.9, y: 0.9 }], previous, ends: true });
  assert.equal(far[0] & 0x0f, 8);
  assert.equal(far.byteLength, 6);
  assert.throws(() => encodePathPoints({ points: [{ x: 0.5, y: 0.51 }], ends: true }));
  assert.equal(decodeLiveDrawing(new Uint8Array([0x18])), null);
});
