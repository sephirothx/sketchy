import assert from "node:assert/strict";
import test from "node:test";

import {
  boundsFromPath,
  distanceToSegmentSquared,
  shapeOutlinePoints,
  toPixels,
} from "../src/lib/canvasGeometry.ts";

test("normalized canvas points convert to protocol pixel coordinates", () => {
  assert.deepEqual(toPixels({ x: 0.25, y: 0.75 }), { x: 200, y: 450 });
});

test("path bounds include the rasterizer safety padding", () => {
  assert.deepEqual(
    boundsFromPath([{ x: 8, y: 20 }, { x: 3, y: 5 }, { x: 12, y: 9 }], 2),
    { minX: 0, minY: 2, maxX: 15, maxY: 23 },
  );
});

test("segment distance clamps to endpoints and handles a zero-length segment", () => {
  assert.equal(distanceToSegmentSquared(2, 3, 0, 0, 4, 0), 9);
  assert.equal(distanceToSegmentSquared(7, 0, 0, 0, 4, 0), 9);
  assert.equal(distanceToSegmentSquared(4, 5, 4, 1, 4, 1), 16);
});

test("rectangle and ellipse outlines are direction-independent", () => {
  const from = { x: 0.3, y: 0.4 };
  const to = { x: 0.1, y: 0.2 };
  assert.deepEqual(shapeOutlinePoints(from, to, "rectangle"), [
    { x: 80, y: 120 },
    { x: 240, y: 120 },
    { x: 240, y: 240 },
    { x: 80, y: 240 },
  ]);
  assert.deepEqual(shapeOutlinePoints(to, from, "rectangle"), shapeOutlinePoints(from, to, "rectangle"));
  assert.deepEqual(shapeOutlinePoints(to, from, "ellipse"), shapeOutlinePoints(from, to, "ellipse"));

  const ellipse = shapeOutlinePoints(from, to, "ellipse");
  assert.equal(ellipse.length, 96);
  assert.deepEqual(ellipse[0], { x: 240, y: 180 });
  assert.ok(Math.abs(ellipse[24].x - 160) < Number.EPSILON * 100);
  assert.equal(ellipse[24].y, 240);
});

test("a triangle dragged upwards stands on the start's row with the start as a corner", () => {
  // Bottom-left to top-right, then bottom-right to top-left: the same triangle.
  const upright = [
    { x: 80, y: 240 },
    { x: 160, y: 120 },
    { x: 240, y: 240 },
  ];
  assert.deepEqual(shapeOutlinePoints({ x: 0.1, y: 0.4 }, { x: 0.3, y: 0.2 }, "triangle"), upright);
  assert.deepEqual(
    shapeOutlinePoints({ x: 0.3, y: 0.4 }, { x: 0.1, y: 0.2 }, "triangle"),
    [...upright].reverse(),
  );
});

test("a triangle dragged downwards is drawn upside down, the start still a corner", () => {
  // Top-left to bottom-right, then top-right to bottom-left (#787).
  const inverted = [
    { x: 80, y: 120 },
    { x: 160, y: 240 },
    { x: 240, y: 120 },
  ];
  assert.deepEqual(shapeOutlinePoints({ x: 0.1, y: 0.2 }, { x: 0.3, y: 0.4 }, "triangle"), inverted);
  assert.deepEqual(
    shapeOutlinePoints({ x: 0.3, y: 0.2 }, { x: 0.1, y: 0.4 }, "triangle"),
    [...inverted].reverse(),
  );
});
