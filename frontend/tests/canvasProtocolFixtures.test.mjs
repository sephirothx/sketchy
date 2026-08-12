import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  calculateCanvasHistoryHash,
  decodeCanvasHistory,
} from "../src/lib/canvasHistory.ts";
import {
  decodeLiveDrawing,
  encodeClear,
  encodeFill,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
  encodeShape,
} from "../src/lib/liveDrawing.ts";

const fixtures = JSON.parse(await readFile(
  new URL("../../fixtures/canvas_protocol_v1.json", import.meta.url),
  "utf8",
));

const encoders = {
  draw_start: encodePathStart,
  draw_move: encodePathPoints,
  draw_end: encodePathEnd,
  draw_shape: encodeShape,
  draw_fill: encodeFill,
  clear_canvas: encodeClear,
};

function bytesFromHex(hex) {
  return Uint8Array.from(hex.match(/../g) ?? [], (byte) => Number.parseInt(byte, 16));
}

function wireHex(value) {
  const bytes = typeof value === "number" ? Uint8Array.of(value) : value;
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

test("versioned canvas protocol goldens match frontend frames, histories, and hashes", () => {
  assert.equal(fixtures.schemaVersion, 1);
  for (const fixture of fixtures.frames) {
    const encoded = encoders[fixture.event](fixture.payload);
    assert.equal(wireHex(encoded), fixture.wire);
    assert.equal(decodeLiveDrawing(encoded)?.event, fixture.event);
  }

  for (const fixture of fixtures.histories) {
    const jsonActions = decodeCanvasHistory(fixture.payload);
    const binaryActions = decodeCanvasHistory(bytesFromHex(fixture.binary));
    assert.deepEqual(binaryActions, jsonActions);
    assert.equal(calculateCanvasHistoryHash(jsonActions), fixture.hash);
  }
});

test("versioned canvas protocol goldens reject malformed versions", () => {
  for (const wire of fixtures.malformedVersions.frames) {
    assert.equal(decodeLiveDrawing(bytesFromHex(wire)), null);
  }
  for (const fixture of fixtures.malformedVersions.histories) {
    const payload = fixture.payload ?? bytesFromHex(fixture.binary);
    assert.equal(decodeCanvasHistory(payload), null);
  }
});
