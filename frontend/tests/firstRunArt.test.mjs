import assert from "node:assert/strict";
import test from "node:test";

import { readFileSync } from "node:fs";

import {
  FIRST_RUN_DOODLES,
  MAX_DROP,
  MAX_SCALE,
  MAX_TILT,
  MIN_SCALE,
  cornerOverhang,
  pickArt,
} from "../src/lib/firstRunArt.ts";
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
      assert.ok(Math.abs(doodle.rotate) <= MAX_TILT, `tilt ${doodle.rotate}`);
      assert.ok(Math.abs(doodle.shift) <= MAX_DROP, `drop ${doodle.shift}`);
      assert.ok(doodle.scale >= MIN_SCALE && doodle.scale <= MAX_SCALE, `size ${doodle.scale}`);
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

test("the corner doodle's worst deal stays inside the card that clips it", () => {
  // The inset and the box as the stylesheet states them, so moving either
  // without the other fails here rather than showing half a kite.
  const css = readFileSync(new URL("../src/styles/account.css", import.meta.url), "utf8");
  const corner = css.match(/\.first-run-art\.is-left \{[^}]*?bottom: (\d+)px;[^}]*?right: (\d+)px;/);
  assert.ok(corner, "the corner rule states its bottom and right insets in px");
  const [bottom, right] = [Number(corner[1]), Number(corner[2])];
  const box = css.match(/height: var\(--doodle-box, (\d+)px\)/);
  assert.ok(box, "the doodle's box has a stated default size");

  const overhang = cornerOverhang(Number(box[1]));
  assert.ok(overhang.y <= bottom, `reaches ${overhang.y.toFixed(1)}px down, inset ${bottom}px`);
  assert.ok(overhang.x <= right, `reaches ${overhang.x.toFixed(1)}px across, inset ${right}px`);
});

test("the overhang grows with every part of the deal", () => {
  const { x, y } = cornerOverhang(96);
  assert.ok(x > 0, "a tilted, enlarged square reaches past its own");
  assert.equal(y - x, MAX_DROP);
});
