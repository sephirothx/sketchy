import assert from "node:assert/strict";
import test from "node:test";

import { shareCredit, shareOffer, sharesAfter } from "../src/lib/shares.ts";
import { laterOf, pendingShareNoticesFrom } from "../src/lib/shareNotices.ts";

const situation = {
  isDrawer: false,
  canAct: true,
  isPublicGame: true,
  shareable: true,
  shares: [],
  mine: "me",
  withdrawn: false,
};

test("anyone who sat in a public game is offered Share, and their own share back", () => {
  assert.equal(shareOffer(situation), "share");
  assert.equal(shareOffer({ ...situation, shares: ["other"] }), "share", "somebody else's share is not mine");
  assert.equal(shareOffer({ ...situation, shares: ["other", "me"] }), "unshare");
});

test("a private room's drawing is offered to its drawer alone", () => {
  assert.equal(shareOffer({ ...situation, isPublicGame: false }), "hidden");
  assert.equal(shareOffer({ ...situation, isPublicGame: false, isDrawer: true }), "share");
});

test("the drawer takes it out for everybody once anybody has shared it", () => {
  const drawer = { ...situation, isDrawer: true };
  assert.equal(shareOffer({ ...drawer, shares: ["other"] }), "takeOut");
  assert.equal(shareOffer({ ...drawer, shares: ["me"] }), "takeOut");
  assert.equal(shareOffer({ ...drawer, withdrawn: true }), "share", "and may put it back");
});

test("after a withdrawal the others are told rather than offered", () => {
  assert.equal(shareOffer({ ...situation, withdrawn: true }), "withdrawn");
});

test("nothing is offered where pressing it cannot work", () => {
  assert.equal(shareOffer({ ...situation, canAct: false }), "hidden", "a spectator or a seat with no account");
  assert.equal(shareOffer({ ...situation, shareable: false }), "hidden", "a blank or unkept drawing");
  assert.equal(
    shareOffer({ ...situation, shareable: false, shares: ["me"] }),
    "unshare",
    "but a share already made can always be taken back",
  );
});

test("the credit is the first sharer, in the viewer's own words", () => {
  const context = {
    mine: "me",
    drawer: "d",
    nameOf: (id) => (id === "ann" ? { name: "Ann", nameColor: "#123456", isAnonymous: false } : null),
  };
  assert.deepEqual(shareCredit([], context), { kind: "none" });
  assert.deepEqual(shareCredit(["me", "ann"], context), { kind: "you" });
  assert.deepEqual(shareCredit(["d"], context), { kind: "drawer" });
  assert.deepEqual(shareCredit(["ann", "me"], context), {
    kind: "player",
    name: "Ann",
    nameColor: "#123456",
    isAnonymous: false,
  });
  assert.deepEqual(shareCredit(["gone"], context), { kind: "someone" }, "a seat that left");
});

test("a press is mirrored the way the room answers it", () => {
  assert.deepEqual(sharesAfter(["a"], "me", true, false), ["a", "me"]);
  assert.deepEqual(sharesAfter(["a", "me"], "me", true, false), ["a", "me"], "a second press moves nobody");
  assert.deepEqual(sharesAfter(["a", "me"], "me", false, false), ["a"]);
  assert.deepEqual(sharesAfter(["a", "me"], "me", false, true), [], "the drawer takes everybody's");
});

test("a pushed notice is read only when it has the right shape, and the newest read wins", () => {
  assert.equal(pendingShareNoticesFrom(null), null);
  assert.equal(pendingShareNoticesFrom({ notices: "x", total: 1 }), null);
  const older = { notices: [{ id: "1", createdAt: "2026-10-07T10:00:00+00:00" }], total: 1 };
  const newer = { notices: [{ id: "2", createdAt: "2026-10-07T11:00:00+00:00" }], total: 2 };
  assert.deepEqual(pendingShareNoticesFrom(newer), newer);
  assert.equal(laterOf(null, older), older);
  assert.equal(laterOf(older, newer), newer);
  assert.equal(laterOf(newer, older), newer);
  assert.equal(laterOf(older, { notices: [], total: 0 }), older);
});
