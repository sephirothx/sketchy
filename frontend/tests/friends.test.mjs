import assert from "node:assert/strict";
import test from "node:test";

import {
  NO_FRIENDS,
  friendActionFor,
  isFriend,
  parseFriendInvite,
  parseFriendLists,
  withFriendsFirst,
} from "../src/lib/friends.ts";

const entry = (userId, extra = {}) => ({
  userId,
  displayName: userId,
  nameColor: "#4f9",
  isAnonymous: false,
  status: "accepted",
  requestedByMe: false,
  createdAt: "2026-09-02T00:00:00Z",
  respondedAt: null,
  ...extra,
});

const player = (userId, extra = {}) => ({
  userId,
  displayName: userId,
  nameColor: "#4f9",
  isAnonymous: false,
  status: "lobby",
  ...extra,
});

const lists = (over = {}) => ({ ...NO_FRIENDS, ...over });

test("a listing keeps only rows this build can read", () => {
  const parsed = parseFriendLists({
    friends: [entry("ada"), { userId: "broken" }, null],
    incoming: [entry("bob", { status: "pending", requestedByMe: false })],
    outgoing: "nonsense",
  });
  assert.deepEqual(parsed.friends.map((e) => e.userId), ["ada"]);
  assert.equal(parsed.incoming[0].status, "pending");
  assert.deepEqual(parsed.outgoing, []);
});

test("a listing from nothing is empty rather than broken", () => {
  for (const bad of [null, undefined, 7, "nope"]) {
    assert.deepEqual(parseFriendLists(bad), NO_FRIENDS);
  }
});

test("the row offers what the relationship actually allows", () => {
  const state = lists({
    friends: [entry("ada")],
    incoming: [entry("bob", { status: "pending" })],
    outgoing: [entry("cleo", { status: "pending", requestedByMe: true })],
  });
  const me = "me";

  // Already friends: nothing to offer.
  assert.equal(friendActionFor(player("ada"), state, me), "none");
  // They asked first, so the button says yes rather than asking again.
  assert.equal(friendActionFor(player("bob"), state, me), "accept");
  assert.equal(friendActionFor(player("cleo"), state, me), "sent");
  assert.equal(friendActionFor(player("dan"), state, me), "add");
});

test("nothing is offered where it could not work", () => {
  const state = lists();
  // A guest has no durable identity to be friends with, and the server
  // refuses one - so the row does not offer a control that always fails.
  assert.equal(
    friendActionFor(player("guest", { isAnonymous: true }), state, "me"),
    "none",
  );
  // Yourself.
  assert.equal(friendActionFor(player("me"), state, "me"), "none");
  // Signed out.
  assert.equal(friendActionFor(player("ada"), state, null), "none");
});

test("friends come first, and the rest keep the order the server sent", () => {
  const state = lists({ friends: [entry("cleo"), entry("ada")] });
  const ordered = withFriendsFirst(
    [player("ada"), player("bob"), player("cleo"), player("dan")],
    state,
  );
  assert.deepEqual(ordered.map((p) => p.userId), ["ada", "cleo", "bob", "dan"]);
});

test("with no friends the list is handed back untouched", () => {
  const players = [player("ada"), player("bob")];
  assert.equal(withFriendsFirst(players, lists()), players);
});

test("isFriend reads accepted friendships only", () => {
  const state = lists({
    friends: [entry("ada")],
    incoming: [entry("bob", { status: "pending" })],
  });
  assert.equal(isFriend(state, "ada"), true);
  assert.equal(isFriend(state, "bob"), false);
});

test("an invitation without a live token is not shown", () => {
  const good = {
    fromUserId: "ada",
    displayName: "Ada",
    inviteToken: "tok",
    expiresIn: 120,
  };
  assert.equal(parseFriendInvite(good).inviteToken, "tok");
  for (const bad of [
    null,
    {},
    { ...good, inviteToken: "" },
    { ...good, fromUserId: "" },
    // Already expired on arrival: a button that cannot work.
    { ...good, expiresIn: 0 },
    { ...good, expiresIn: "soon" },
  ]) {
    assert.equal(parseFriendInvite(bad), null);
  }
});

test("an invitation with no name still says somebody sent it", () => {
  const parsed = parseFriendInvite({
    fromUserId: "ada",
    inviteToken: "tok",
    expiresIn: 60,
  });
  assert.equal(parsed.displayName, "A friend");
});
