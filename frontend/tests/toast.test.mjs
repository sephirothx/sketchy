import assert from "node:assert/strict";
import test from "node:test";

import { MAX_TOASTS, keepRecentToasts, sameToast } from "../src/lib/toast.ts";

const stack = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }));
// The stack rules on their own: no toast repeats another.
const never = () => false;

test("a toast arriving on an empty screen stands alone", () => {
  const { kept, evicted } = keepRecentToasts([], { id: 9 }, never);
  assert.deepEqual(kept, [{ id: 9 }]);
  assert.deepEqual(evicted, []);
});

test("the stack fills to the cap without dropping anything", () => {
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS - 1), { id: 99 }, never);
  assert.equal(kept.length, MAX_TOASTS);
  assert.deepEqual(evicted, []);
});

test("past the cap the oldest falls off, newest last", () => {
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS), { id: 99 }, never);
  assert.equal(kept.length, MAX_TOASTS);
  assert.deepEqual(evicted, [{ id: 1 }]);
  assert.deepEqual(kept.at(-1), { id: 99 });
});

test("whatever falls off is handed back, so its timer can be cleared", () => {
  // A dropped toast whose timer still runs leaves an entry behind and fires a
  // dismissal for something nobody can see.
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS + 3), { id: 99 }, never);
  assert.equal(kept.length, MAX_TOASTS);
  assert.equal(evicted.length, 4);
  assert.deepEqual(
    evicted.map((toast) => toast.id),
    [1, 2, 3, 4],
  );
});

test("a toast arriving on a screen below the cap evicts nothing", () => {
  const { kept, evicted } = keepRecentToasts(stack(1), { id: 42 }, never);
  assert.deepEqual(evicted, []);
  assert.ok(kept.some((toast) => toast.id === 42));
});

test("a toast saying what one on screen says replaces it rather than stacking", () => {
  const same = (a, b) => a.message === b.message;
  const current = [{ id: 1, message: "other" }, { id: 2, message: "too short" }];
  const { kept, evicted } = keepRecentToasts(current, { id: 3, message: "too short" }, same);
  assert.deepEqual(kept.map((t) => t.id), [1, 3]);
  assert.deepEqual(evicted.map((t) => t.id), [2]);
  // Without the rule, nothing is treated as a repeat.
  assert.equal(keepRecentToasts(current, { id: 3, message: "too short" }, never).kept.length, 3);
});

test("a repeat is the same words in the same tone, with nothing to act on", () => {
  const refusal = { message: "Too short", tone: "error" };
  assert.equal(sameToast(refusal, { message: "Too short", tone: "error" }), true);
  assert.equal(sameToast(refusal, { message: "Too long", tone: "error" }), false);
  // The same words as a warning are something else to say.
  assert.equal(sameToast(refusal, { message: "Too short", tone: "warning" }), false);
  // An action is its own offer, on either side.
  const offer = { message: "Too short", tone: "error", action: { label: "Fix", onClick() {} } };
  assert.equal(sameToast(refusal, offer), false);
  assert.equal(sameToast(offer, refusal), false);
  assert.equal(sameToast(offer, offer), false);
});
