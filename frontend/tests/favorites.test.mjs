import assert from "node:assert/strict";
import test from "node:test";

import {
  FAVORITE_SLOTS,
  isFavorite,
  moveFavorite,
  favoriteEligibility,
  favoritesAsRecapEntries,
  favoriteSetTo,
  rebaseFavorites,
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

test("a press says what it wants, so a list it never saw cannot reverse it", () => {
  assert.deepEqual(favoriteSetTo(["b"], "b", true), ["b"]);
  assert.deepEqual(favoriteSetTo(["a"], "b", true), ["a", "b"]);
  assert.deepEqual(favoriteSetTo(["a"], "b", false), ["a"]);
  assert.deepEqual(favoriteSetTo(["a", "b"], "b", false), ["a"]);
  assert.equal(favoriteSetTo(six, "g", true), null);
  // Already on a full shelf is not a refusal: nothing is left to do.
  assert.deepEqual(favoriteSetTo(six, "a", true), six);
  // The store runs a mutation again on a reread after a 404 (#1523 review):
  // this tab held [a], a left the Gallery, another tab added b. The add sent
  // [a, b]; on the reread [b] it must leave b in, not take it out.
  const add = (current) => favoriteSetTo(current, "b", true);
  assert.deepEqual(add(["a"]), ["a", "b"]);
  assert.deepEqual(add(["b"]), ["b"]);
});

test("an arranged shelf keeps its removals and order over a list that moved on", () => {
  // Arranged from [a, b, c]: c taken off, b moved first. Since then the
  // server dropped a and another control added d.
  assert.deepEqual(rebaseFavorites(["b", "a"], ["a", "b", "c"], ["b", "c", "d"]), ["b", "d"]);
  assert.deepEqual(rebaseFavorites(["b", "a"], ["a", "b"], ["a", "b"]), ["b", "a"]);
});
