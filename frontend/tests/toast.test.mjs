import assert from "node:assert/strict";
import test from "node:test";

import { MAX_TOASTS, keepRecentToasts } from "../src/lib/toast.ts";

const stack = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }));

test("a toast arriving on an empty screen stands alone", () => {
  const { kept, evicted } = keepRecentToasts([], { id: 9 });
  assert.deepEqual(kept, [{ id: 9 }]);
  assert.deepEqual(evicted, []);
});

test("the stack fills to the cap without dropping anything", () => {
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS - 1), { id: 99 });
  assert.equal(kept.length, MAX_TOASTS);
  assert.deepEqual(evicted, []);
});

test("past the cap the oldest falls off, newest last", () => {
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS), { id: 99 });
  assert.equal(kept.length, MAX_TOASTS);
  assert.deepEqual(evicted, [{ id: 1 }]);
  assert.deepEqual(kept.at(-1), { id: 99 });
});

test("whatever falls off is handed back, so its timer can be cleared", () => {
  // A dropped toast whose timer still runs leaves an entry behind and fires a
  // dismissal for something nobody can see.
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS + 3), { id: 99 });
  assert.equal(kept.length, MAX_TOASTS);
  assert.equal(evicted.length, 4);
  assert.deepEqual(
    evicted.map((toast) => toast.id),
    [1, 2, 3, 4],
  );
});

test("a toast arriving on a screen below the cap evicts nothing", () => {
  const { kept, evicted } = keepRecentToasts(stack(1), { id: 42 });
  assert.deepEqual(evicted, []);
  assert.ok(kept.some((toast) => toast.id === 42));
});
