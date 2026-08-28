import assert from "node:assert/strict";
import test from "node:test";

import { admissionLabel, isAdmitting } from "../src/lib/adminControls.ts";

test("an ordinary server says it is taking rooms", () => {
  assert.equal(
    admissionLabel({ paused: false, draining: false }),
    "accepting rooms",
  );
  assert.equal(isAdmitting({ paused: false, draining: false }), true);
});

test("a paused server does not claim to be taking rooms", () => {
  // The banner is the first thing an administrator reads, and it said
  // "accepting rooms" unconditionally - the opposite of the truth during a
  // maintenance pause, which is exactly when somebody is looking at it.
  assert.equal(admissionLabel({ paused: true, draining: false }), "paused — no new rooms");
  assert.equal(isAdmitting({ paused: true, draining: false }), false);
});

test("a draining server says so, and says it before a pause", () => {
  // Both can be true at once; the drain is the one that ends the process.
  assert.equal(
    admissionLabel({ paused: true, draining: true }),
    "draining — no new rooms",
  );
  assert.equal(isAdmitting({ paused: false, draining: true }), false);
});

test("an unknown state does not assert that rooms are being taken", () => {
  // Before the first load. "accepting rooms" is the honest default only
  // because it is what an unpaused server does; the tone must not shout.
  assert.equal(admissionLabel(null), "accepting rooms");
});
