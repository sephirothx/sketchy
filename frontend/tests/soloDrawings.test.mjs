import assert from "node:assert/strict";
import test from "node:test";

import { DecodedDrawings } from "../src/lib/soloDrawings.ts";

const bytes = (...values) => new Uint8Array(values).buffer;

function counting() {
  const decode = (buffer) => {
    decode.calls += 1;
    return [...new Uint8Array(buffer)];
  };
  decode.calls = 0;
  return decode;
}

test("the same bytes from the door again are not decoded again", () => {
  const drawings = new DecodedDrawings();
  const decode = counting();
  const first = drawings.decode("serve", bytes(1, 2, 3), decode);
  const again = drawings.decode("serve", bytes(1, 2, 3), decode);
  assert.equal(decode.calls, 1);
  assert.equal(again, first);
});

test("other bytes under the same serve are decoded afresh", () => {
  const drawings = new DecodedDrawings();
  const decode = counting();
  drawings.decode("serve", bytes(1, 2, 3), decode);
  assert.deepEqual(drawings.decode("serve", bytes(3, 2, 1), decode), [3, 2, 1]);
  assert.equal(decode.calls, 2);
});

test("a drawing the door refused is forgotten, so its next showing decodes what the door gives then", () => {
  const drawings = new DecodedDrawings();
  const decode = counting();
  drawings.decode("serve", bytes(1, 2, 3), decode);
  drawings.forget("serve");
  assert.equal(drawings.size, 0);
  drawings.decode("serve", bytes(1, 2, 3), decode);
  assert.equal(decode.calls, 2);
});

test("bytes that do not decode keep nothing", () => {
  const drawings = new DecodedDrawings();
  assert.equal(drawings.decode("serve", bytes(9), () => null), null);
  assert.equal(drawings.size, 0);
});

test("it keeps the drawings shown last, and an account's page clears them", () => {
  const drawings = new DecodedDrawings(2);
  const decode = counting();
  drawings.decode("a", bytes(1), decode);
  drawings.decode("b", bytes(2), decode);
  drawings.decode("a", bytes(1), decode);
  drawings.decode("c", bytes(3), decode);
  assert.equal(drawings.size, 2);
  drawings.decode("a", bytes(1), decode);
  assert.equal(decode.calls, 3, "a, shown again before c, was kept; b went");
  drawings.clear();
  assert.equal(drawings.size, 0);
});
