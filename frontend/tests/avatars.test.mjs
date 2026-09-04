import assert from "node:assert/strict";
import test from "node:test";

import {
  AVATAR_SIZE,
  MAX_AVATAR_BYTES,
  MAX_ZOOM,
  centreSquare,
  clampCrop,
  cropRect,
  initialCrop,
  maxZoomFor,
  viewportPlacement,
} from "../src/lib/avatarCrop.ts";

test("the default crop is the largest square centred on the picture", () => {
  assert.deepEqual(centreSquare(400, 300), { x: 50, y: 0, side: 300 });
  assert.deepEqual(centreSquare(300, 400), { x: 0, y: 50, side: 300 });
  assert.deepEqual(centreSquare(256, 256), { x: 0, y: 0, side: 256 });
  // An odd remainder lands on the leading side, never off the picture.
  assert.deepEqual(centreSquare(301, 300), { x: 0, y: 0, side: 300 });
  // And the framing model starts from the same square.
  assert.deepEqual(cropRect(400, 300, initialCrop(400, 300)), { x: 50, y: 0, side: 300 });
});

test("zooming in shrinks the square around the same point", () => {
  const crop = { zoom: 2, centerX: 200, centerY: 150 };
  assert.deepEqual(cropRect(400, 300, crop), { x: 125, y: 75, side: 150 });
});

test("the square never leaves the picture, however it is dragged or zoomed", () => {
  // Dragged past every edge: pulled back to the corner, not off the picture.
  assert.deepEqual(cropRect(400, 300, { zoom: 1, centerX: -50, centerY: 900 }), {
    x: 0,
    y: 0,
    side: 300,
  });
  assert.deepEqual(cropRect(400, 300, { zoom: 2, centerX: 1e9, centerY: 1e9 }), {
    x: 250,
    y: 150,
    side: 150,
  });
  // Zoomed out past 1 is still 1; zoomed in past the cap is the cap.
  assert.equal(clampCrop(400, 300, { zoom: 0.2, centerX: 200, centerY: 150 }).zoom, 1);
  assert.equal(clampCrop(400, 300, { zoom: 99, centerX: 200, centerY: 150 }).zoom, MAX_ZOOM);
  // A small picture cannot zoom to a square smaller than the minimum.
  assert.equal(maxZoomFor(64, 64), 2);
  assert.equal(maxZoomFor(20, 20), 1);
});

test("the viewport shows exactly the cropped square", () => {
  const placement = viewportPlacement(400, 300, { zoom: 1, centerX: 200, centerY: 150 }, 300);
  assert.deepEqual(placement, { scale: 1, left: -50, top: 0 });
  const zoomed = viewportPlacement(400, 300, { zoom: 2, centerX: 200, centerY: 150 }, 300);
  assert.equal(zoomed.scale, 2);
  // The crop's top-left (125, 75) lands on the viewport's top-left.
  assert.equal(zoomed.left + 125 * zoomed.scale, 0);
  assert.equal(zoomed.top + 75 * zoomed.scale, 0);
});

test("the client's limits are the server's", () => {
  assert.equal(AVATAR_SIZE, 256);
  assert.equal(MAX_AVATAR_BYTES, 128 * 1024);
});
