import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_GALLERY_FILTERS,
  galleryEntriesAsRecap,
  galleryFiltersFromParams,
  paramsFromGalleryFilters,
} from "../src/lib/gallery.ts";

test("an order survives being shared as a link", () => {
  const filters = { sort: "top", window: "week" };

  assert.deepEqual(galleryFiltersFromParams(paramsFromGalleryFilters(filters)), filters);
});

test("the default view carries no parameters at all", () => {
  assert.equal(paramsFromGalleryFilters(DEFAULT_GALLERY_FILTERS).toString(), "");
});

test("a link nobody could have been given reads as the default", () => {
  // The only way to hold these is to have edited the URL, and a page that
  // refuses to render is worse than one that shows what is hot.
  const params = new URLSearchParams("sort=sideways&window=fortnight");

  assert.deepEqual(galleryFiltersFromParams(params), DEFAULT_GALLERY_FILTERS);
});

test("a window is kept as parsed even when the order is not Top", () => {
  // Switching Top → New → Top should come back to the same window.
  const params = new URLSearchParams("sort=new&window=month");

  assert.deepEqual(galleryFiltersFromParams(params), { sort: "new", window: "month" });
  assert.equal(paramsFromGalleryFilters({ sort: "new", window: "month" }).toString(), "sort=new&window=month");
});

test("entries become recap entries in page order, with no drawer id", () => {
  const entry = {
    turnId: "t1",
    roundNumber: 2,
    turnNumber: 3,
    drawerDisplayName: "Ada",
    drawerNameColor: "#123456",
    drawerIsAnonymous: false,
    prompt: "cat",
    strokeCount: 40,
    finishedAt: "2026-09-15T10:00:00Z",
    reactionCounts: { "❤️": 2 },
    myReaction: null,
    drawnByMe: false,
  };

  const [first, second] = galleryEntriesAsRecap([entry, { ...entry, turnId: "t2", drawerNameColor: null }]);

  assert.deepEqual(first, {
    index: 0,
    turnId: "t1",
    roundNumber: 2,
    turnNumber: 3,
    drawerId: "",
    drawerNickname: "Ada",
    drawerNameColor: "#123456",
    prompt: "cat",
    actionCount: 40,
    available: true,
  });
  assert.equal(second.index, 1);
  assert.equal(second.turnId, "t2");
  assert.equal(second.drawerNameColor, undefined);
});
