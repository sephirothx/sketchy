import assert from "node:assert/strict";
import test from "node:test";

import {
  ROOM_FILTERS_FROM,
  linksToGallery,
  showsRoomCount,
  showsRoomFilters,
} from "../src/lib/lobbyControls.ts";

test("search and filters appear from six rooms, not before", () => {
  assert.equal(ROOM_FILTERS_FROM, 6);
  assert.equal(showsRoomFilters({ roomCount: 5, narrowing: false, alreadyShown: false }), false);
  assert.equal(showsRoomFilters({ roomCount: 6, narrowing: false, alreadyShown: false }), true);
});

test("a search or a filter that is on keeps them, whatever the count", () => {
  assert.equal(showsRoomFilters({ roomCount: 0, narrowing: true, alreadyShown: false }), true);
});

test("once shown they stay, so a live list never unmounts the box being typed in", () => {
  assert.equal(showsRoomFilters({ roomCount: 2, narrowing: false, alreadyShown: true }), true);
});

test("the count appears only when a filter left rooms out", () => {
  assert.equal(showsRoomCount({ loaded: false, shown: 0, total: 0 }), false);
  assert.equal(showsRoomCount({ loaded: true, shown: 0, total: 0 }), false);
  assert.equal(showsRoomCount({ loaded: true, shown: 1, total: 1 }), false);
  assert.equal(showsRoomCount({ loaded: true, shown: 3, total: 12 }), true);
});

test("the Gallery is linked only with a session (R-GAL-02)", () => {
  assert.equal(linksToGallery(null), false);
  assert.equal(linksToGallery(undefined), false);
  assert.equal(linksToGallery({ id: "u1", isAnonymous: true }), true);
});
