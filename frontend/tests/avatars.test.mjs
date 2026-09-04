import assert from "node:assert/strict";
import test from "node:test";

import { AVATAR_SIZE, MAX_AVATAR_BYTES, centreSquare } from "../src/lib/avatarCrop.ts";

test("the crop is the largest square centred on the picture", () => {
  assert.deepEqual(centreSquare(400, 300), { x: 50, y: 0, side: 300 });
  assert.deepEqual(centreSquare(300, 400), { x: 0, y: 50, side: 300 });
  assert.deepEqual(centreSquare(256, 256), { x: 0, y: 0, side: 256 });
  // An odd remainder lands on the leading side, never off the picture.
  assert.deepEqual(centreSquare(301, 300), { x: 0, y: 0, side: 300 });
});

test("the client's limits are the server's", () => {
  assert.equal(AVATAR_SIZE, 256);
  assert.equal(MAX_AVATAR_BYTES, 128 * 1024);
});
