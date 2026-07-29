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

test("live drawing frames round-trip with compact fixed sizes", () => {
  const cases = [
    [encodePathStart({ x: 0.25, y: 0.75, color: "#aabbcc", width: 4 }), "draw_start", 9],
    [encodePathPoints({ points: [{ x: 0.1, y: 0.2 }, { x: 1.2, y: -0.1 }] }), "draw_move", 9],
    [encodePathEnd(), "draw_end", 1],
    [encodeShape({
      shape: "ellipse",
      from: { x: 0.1, y: 0.2 },
      to: { x: 0.8, y: 0.9 },
      color: "#123456",
      width: 64,
    }), "draw_shape", 14],
    [encodeFill({ x: 0.25, y: 0.75, color: "#fedcba" }), "draw_fill", 8],
    [encodeClear(), "clear_canvas", 1],
  ];

  for (const [frame, event, size] of cases) {
    assert.equal(frame.byteLength, size);
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
});

test("fill coordinates preserve the addressed canvas pixel", () => {
  const packet = decodeLiveDrawing(
    encodeFill({ x: 0.9999, y: 0.9999, color: "#abcdef" }),
  );
  assert.deepEqual(packet, {
    event: "draw_fill",
    payload: { x: 799 / 800, y: 599 / 600, color: "#abcdef" },
  });
});
