import assert from "node:assert/strict";
import test from "node:test";

import { FIRST_RUN_DOODLES, pickArt } from "../src/lib/firstRunArt.ts";
import { DOODLES } from "../src/lib/avatarDoodles.ts";

/** A roll that walks a known sequence, so a deal can be asserted exactly. */
function rolls(values) {
  let index = 0;
  return () => values[index++ % values.length];
}

test("three different doodles, dealt to the two sides of the tag", () => {
  const art = pickArt(DOODLES, Math.random);
  const names = [...art.left, ...art.right].map((doodle) => doodle.name);
  assert.equal(names.length, FIRST_RUN_DOODLES);
  assert.equal(new Set(names).size, FIRST_RUN_DOODLES, `dealt a doodle twice: ${names}`);
  for (const name of names) assert.ok(DOODLES.includes(name), name);
  assert.ok(art.left.length >= 1 && art.right.length >= 1, "both sides get one");
});

test("a deal is the same in the same order, and every tilt, drop and size is small", () => {
  for (let seed = 0; seed < 50; seed += 1) {
    const art = pickArt(DOODLES, Math.random);
    for (const doodle of [...art.left, ...art.right]) {
      assert.ok(Math.abs(doodle.rotate) <= 9, `tilt ${doodle.rotate}`);
      assert.ok(Math.abs(doodle.shift) <= 14, `drop ${doodle.shift}`);
      assert.ok(doodle.scale >= 0.85 && doodle.scale <= 1.15, `size ${doodle.scale}`);
    }
  }
});

test("the deal follows the rolls it is given", () => {
  const art = pickArt(["a", "b", "c", "d"], rolls([0.9, 0, 0.5, 0.5, 0.5, 0, 0.5, 0.5, 0.5, 0, 0.5, 0.5, 0.5]));
  // First roll 0.9: two doodles left, one right.
  assert.equal(art.left.length, 2);
  assert.equal(art.right.length, 1);
  assert.deepEqual([...art.left, ...art.right].map((d) => d.name), ["a", "b", "c"]);
  assert.equal(art.left[0].rotate, 0);
  assert.equal(art.left[0].shift, 0);
  assert.equal(art.left[0].scale, 1);
});

test("a pool with fewer doodles than the card wants deals what there is", () => {
  const two = pickArt(["a", "b"], Math.random);
  assert.equal([...two.left, ...two.right].length, 2);
  const one = pickArt(["a"], Math.random);
  assert.equal([...one.left, ...one.right].length, 1);
  assert.equal(pickArt([], Math.random).left.length, 0);
});

test("it is not the same three every time", () => {
  const deals = new Set();
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const art = pickArt(DOODLES, Math.random);
    deals.add([...art.left, ...art.right].map((d) => d.name).join(","));
  }
  assert.ok(deals.size > 5, `only ${deals.size} different deals in 40`);
});
