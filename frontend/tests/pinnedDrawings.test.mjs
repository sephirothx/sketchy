import assert from "node:assert/strict";
import test from "node:test";

import {
  PINNED_DRAWING_SLOTS,
  isPinned,
  movePin,
  pinsAsRecapEntries,
  shelfIsFull,
  shelfPresence,
  withPin,
  withoutPin,
} from "../src/lib/pinnedDrawings.ts";

const six = ["a", "b", "c", "d", "e", "f"];

test("the shelf is absent for a signed-out viewer, whatever is pinned", () => {
  assert.equal(shelfPresence({ viewerSignedIn: false, isOwner: false, count: 3 }), "absent");
  assert.equal(shelfPresence({ viewerSignedIn: false, isOwner: true, count: 0 }), "absent");
});

test("an empty shelf is shown only to its owner", () => {
  assert.equal(shelfPresence({ viewerSignedIn: true, isOwner: true, count: 0 }), "empty");
  assert.equal(shelfPresence({ viewerSignedIn: true, isOwner: false, count: 0 }), "absent");
  assert.equal(shelfPresence({ viewerSignedIn: true, isOwner: false, count: 1 }), "shelf");
});

test("pinning appends until the six slots are taken", () => {
  assert.deepEqual(withPin(["a"], "b"), ["a", "b"]);
  assert.equal(withPin(["a"], "a"), null, "already pinned");
  assert.equal(shelfIsFull(six), true);
  assert.equal(PINNED_DRAWING_SLOTS, 6);
  assert.equal(withPin(six, "g"), null, "full");
  assert.equal(isPinned(six, "f"), true);
});

test("unpinning keeps the order of what remains", () => {
  assert.deepEqual(withoutPin(six, "c"), ["a", "b", "d", "e", "f"]);
  assert.deepEqual(withoutPin(six, "zz"), six);
});

test("moving swaps a neighbour and stops at the edges", () => {
  assert.deepEqual(movePin(six, 0, 1), ["b", "a", "c", "d", "e", "f"]);
  assert.deepEqual(movePin(six, 5, -1), ["a", "b", "c", "d", "f", "e"]);
  assert.deepEqual(movePin(six, 0, -1), six, "left edge");
  assert.deepEqual(movePin(six, 5, 1), six, "right edge");
  assert.deepEqual(movePin(six, 9, 1), six, "no such index");
  assert.notEqual(movePin(six, 0, 0), six, "always a copy");
});

test("recap entries follow shelf order and carry no seat", () => {
  const entries = pinsAsRecapEntries([
    {
      turnId: "t2",
      roundNumber: 2,
      turnNumber: 1,
      drawerDisplayName: "Ann",
      drawerNameColor: null,
      drawerIsAnonymous: false,
      prompt: "jackpot",
      strokeCount: 12,
      reactions: [],
    },
  ]);
  assert.deepEqual(entries, [
    {
      index: 0,
      turnId: "t2",
      roundNumber: 2,
      turnNumber: 1,
      drawerId: "",
      drawerNickname: "Ann",
      drawerNameColor: undefined,
      prompt: "jackpot",
      actionCount: 12,
      available: true,
    },
  ]);
});
