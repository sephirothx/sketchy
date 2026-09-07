import assert from "node:assert/strict";
import test from "node:test";

import {
  FIRST_RETRY_MS,
  MAX_RETRY_MS,
  resubscribeDelayMs,
} from "../src/lib/lobbyChannel.ts";

test("the first retry is soon and the rest back off", () => {
  assert.equal(resubscribeDelayMs(1), FIRST_RETRY_MS);
  assert.equal(resubscribeDelayMs(2), 2000);
  assert.equal(resubscribeDelayMs(3), 4000);
  assert.equal(resubscribeDelayMs(4), 8000);
});

test("the wait is capped, so a recovery is noticed promptly", () => {
  // A server refusing every subscription still hears from each open lobby, so
  // this cannot grow without bound - and it must not shrink to a retry loop
  // that is itself the outage.
  for (const attempt of [10, 50, 1000]) {
    assert.equal(resubscribeDelayMs(attempt), MAX_RETRY_MS, String(attempt));
  }
});

test("a nonsense attempt still yields a usable wait", () => {
  for (const attempt of [0, -1, Number.NaN]) {
    assert.equal(resubscribeDelayMs(attempt), FIRST_RETRY_MS, String(attempt));
  }
});

// --- deltas that beat the baseline (#600) -----------------------------------

import { MAX_HELD_DELTAS, createPendingDeltas } from "../src/lib/lobbyChannel.ts";

test("a delta held before the baseline is replayed after it, if newer, in order", () => {
  const pending = createPendingDeltas();
  assert.equal(pending.hold("rooms", { revision: 7, closed: ["r1"] }), true);
  assert.equal(pending.hold("rooms", { revision: 6, opened: [] }), true);
  assert.equal(pending.hold("presence", { revision: 3 }), true);
  assert.equal(pending.hold("chat", { seq: 12, text: "hi" }), true);
  const replayed = pending.drain({ presence: 3, rooms: 6, chatSeq: 11 });
  assert.deepEqual(
    replayed.map((d) => [d.feed, d.at]),
    [["rooms", 7], ["chat", 12]],
    "at or below the baseline is already inside it; the rest, oldest first",
  );
  assert.equal(pending.size, 0);
});

test("the final delta before a quiet spell needs no later delta to repair it", () => {
  // The reproduced case: baseline captured at R, a room closes at R+1 while
  // the answer is pending, then nothing else happens.
  const pending = createPendingDeltas();
  pending.hold("rooms", { revision: 1, closed: ["stale-room"] });
  const replayed = pending.drain({ presence: 0, rooms: 0, chatSeq: 0 });
  assert.deepEqual(replayed.map((d) => d.at), [1]);
});

test("junk is not held and a cleared buffer holds nothing", () => {
  const pending = createPendingDeltas();
  assert.equal(pending.hold("rooms", "nope"), true);
  assert.equal(pending.hold("rooms", { revision: -1 }), true);
  assert.equal(pending.size, 0);
  pending.hold("presence", { revision: 2 });
  pending.clear();
  assert.deepEqual(pending.drain({ presence: 0, rooms: 0, chatSeq: 0 }), []);
});

test("past the cap the buffer gives up and asks for a fresh baseline instead", () => {
  const pending = createPendingDeltas(3);
  assert.equal(pending.hold("rooms", { revision: 1 }), true);
  assert.equal(pending.hold("rooms", { revision: 2 }), true);
  assert.equal(pending.hold("rooms", { revision: 3 }), true);
  assert.equal(pending.hold("rooms", { revision: 4 }), false, "overflow");
  assert.equal(pending.hold("rooms", { revision: 5 }), false, "stays overflowed until drained or cleared");
  assert.equal(pending.size, 0, "what it held no longer joins onto anything");
  pending.drain({ presence: 0, rooms: 0, chatSeq: 0 });
  assert.equal(pending.hold("rooms", { revision: 9 }), true, "a drain resets it");
  assert.equal(MAX_HELD_DELTAS, 64);
});
