import assert from "node:assert/strict";
import test from "node:test";

import {
  FAVORITE_SLOTS,
  isFavorite,
  moveFavorite,
  moveFavoriteTo,
  hiddenPromptShape,
  favoriteEligibility,
  favoritesAsRecapEntries,
  shelfIsFull,
  shelfPresence,
  withFavorite,
  withoutFavorite,
} from "../src/lib/favorites.ts";

const six = ["a", "b", "c", "d", "e", "f"];

test("the shelf is absent for a signed-out viewer, whatever is favorited", () => {
  assert.equal(shelfPresence({ viewerSignedIn: false, isOwner: false, count: 3 }), "absent");
  assert.equal(shelfPresence({ viewerSignedIn: false, isOwner: true, count: 0 }), "absent");
});

test("an empty shelf is shown only to its owner", () => {
  assert.equal(shelfPresence({ viewerSignedIn: true, isOwner: true, count: 0 }), "empty");
  assert.equal(shelfPresence({ viewerSignedIn: true, isOwner: false, count: 0 }), "absent");
  assert.equal(shelfPresence({ viewerSignedIn: true, isOwner: false, count: 1 }), "shelf");
});

test("favoriting appends until the six slots are taken", () => {
  assert.deepEqual(withFavorite(["a"], "b"), ["a", "b"]);
  assert.equal(withFavorite(["a"], "a"), null, "already favorited");
  assert.equal(shelfIsFull(six), true);
  assert.equal(FAVORITE_SLOTS, 6);
  assert.equal(withFavorite(six, "g"), null, "full");
  assert.equal(isFavorite(six, "f"), true);
});

test("unfavoriting keeps the order of what remains", () => {
  assert.deepEqual(withoutFavorite(six, "c"), ["a", "b", "d", "e", "f"]);
  assert.deepEqual(withoutFavorite(six, "zz"), six);
});

test("moving swaps a neighbour and stops at the edges", () => {
  assert.deepEqual(moveFavorite(six, 0, 1), ["b", "a", "c", "d", "e", "f"]);
  assert.deepEqual(moveFavorite(six, 5, -1), ["a", "b", "c", "d", "f", "e"]);
  assert.deepEqual(moveFavorite(six, 0, -1), six, "left edge");
  assert.deepEqual(moveFavorite(six, 5, 1), six, "right edge");
  assert.deepEqual(moveFavorite(six, 9, 1), six, "no such index");
  assert.notEqual(moveFavorite(six, 0, 0), six, "always a copy");
});

test("a Favorite control is offered only where the write can succeed", () => {
  const base = { isRegistered: true, isSpectator: false, isPublicGame: true, open: true };
  assert.equal(favoriteEligibility(base), "offered");
  assert.equal(favoriteEligibility({ ...base, isRegistered: false }), "hidden", "a guest");
  assert.equal(favoriteEligibility({ ...base, isSpectator: true }), "hidden", "a spectator");
  assert.equal(favoriteEligibility({ ...base, isPublicGame: false }), "hidden", "a private room");
  assert.equal(favoriteEligibility({ ...base, open: false }), "hidden", "a drawing not kept");
  assert.equal(favoriteEligibility({ isRegistered: true, isPublicGame: true, open: true }), "offered");
});

test("a favorite is a share: the drawer may favorite from any game, nobody favorites a withdrawn or blank one", () => {
  const base = { isRegistered: true, isPublicGame: false, open: true };
  assert.equal(favoriteEligibility({ ...base, isDrawer: true }), "offered", "the drawer's own private drawing");
  assert.equal(favoriteEligibility({ ...base, isDrawer: false }), "hidden", "somebody else's private drawing");
  assert.equal(
    favoriteEligibility({ ...base, isPublicGame: true, withdrawn: true }),
    "hidden",
    "its drawer took it out",
  );
  assert.equal(
    favoriteEligibility({ ...base, isPublicGame: true, withdrawn: true, isDrawer: true }),
    "offered",
    "the drawer may put it back",
  );
  assert.equal(favoriteEligibility({ ...base, isDrawer: true, blank: true }), "hidden", "nothing was drawn");
});

test("recap entries follow shelf order and carry no seat", () => {
  const entries = favoritesAsRecapEntries([
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
      reactionCounts: {},
      myReaction: null,
      drawnByMe: false,
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
      // So the recap credits a guest in the guest style (#1279).
      drawerIsAnonymous: false,
      prompt: "jackpot",
      actionCount: 12,
      available: true,
    },
  ]);
});

test("a drawing moved to a place takes it, and the others close up around it", () => {
  const shelf = ["a", "b", "c", "d"];
  assert.deepEqual(moveFavoriteTo(shelf, "a", 2), ["b", "c", "a", "d"]);
  assert.deepEqual(moveFavoriteTo(shelf, "d", 0), ["d", "a", "b", "c"]);
  assert.deepEqual(moveFavoriteTo(shelf, "b", 1), shelf);
  assert.deepEqual(moveFavoriteTo(shelf, "x", 0), shelf, "an unknown drawing changes nothing");
  assert.deepEqual(moveFavoriteTo(shelf, "a", 4), shelf, "nor does a place past the end");
});

test("a hidden prompt keeps its word breaks and punctuation, and counts letters per run", () => {
  const sleepy = hiddenPromptShape("sleepy cat");
  assert.deepEqual(sleepy.counts, [6, 3]);
  assert.equal(sleepy.words.length, 2);
  const banded = hiddenPromptShape("band-aid");
  assert.deepEqual(banded.counts, [4, 3]);
  assert.deepEqual(banded.words[0].map((segment) => segment.kind), ["tiles", "glyph", "tiles"]);
  assert.equal(JSON.stringify(banded).includes("b"), false, "no letter of the prompt survives");
  assert.deepEqual(hiddenPromptShape("città").counts, [5], "an accented letter is a tile");
});
