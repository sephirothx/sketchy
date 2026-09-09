import assert from "node:assert/strict";
import test from "node:test";

import {
  NO_FRIENDS,
  friendListChanges,
  friendsSurface,
  friendsSurfaceIsEmpty,
  isFriend,
  addableRecentPlayers,
  parseFriendInvite,
  parseFriendLists,
  parseRecentPlayers,
  profileFriendActionFor,
  waitingRequestCount,
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

// --------------------------------------------------- the friends surface

const surfaceEntry = (userId, extra = {}) => entry(userId, extra);

test("the surface orders requests newest first and friends by name", () => {
  const { incoming, outgoing, friends } = friendsSurface({
    friends: [
      surfaceEntry("zoe", { displayName: "Zoe" }),
      surfaceEntry("ana", { displayName: "ana" }),
      surfaceEntry("bob", { displayName: "Bob" }),
    ],
    incoming: [
      surfaceEntry("old", { createdAt: "2026-01-01T00:00:00Z" }),
      surfaceEntry("new", { createdAt: "2026-09-01T00:00:00Z" }),
    ],
    outgoing: [
      surfaceEntry("sent-old", { createdAt: "2026-02-01T00:00:00Z" }),
      surfaceEntry("sent-new", { createdAt: "2026-08-01T00:00:00Z" }),
    ],
  });
  assert.deepEqual(incoming.map((row) => row.userId), ["new", "old"]);
  assert.deepEqual(outgoing.map((row) => row.userId), ["sent-new", "sent-old"]);
  // Case-insensitively, so "ana" is not exiled after "Zoe".
  assert.deepEqual(friends.map((row) => row.userId), ["ana", "bob", "zoe"]);
});

test("the surface does not reorder the lists it was handed", () => {
  const lists = {
    ...NO_FRIENDS,
    incoming: [
      surfaceEntry("old", { createdAt: "2026-01-01T00:00:00Z" }),
      surfaceEntry("new", { createdAt: "2026-09-01T00:00:00Z" }),
    ],
  };
  friendsSurface(lists);
  assert.deepEqual(lists.incoming.map((row) => row.userId), ["old", "new"]);
});

test("a surface is empty only when all three groups are", () => {
  assert.equal(friendsSurfaceIsEmpty(friendsSurface(NO_FRIENDS)), true);
  // One waiting request is not an empty screen, even with no friends at all.
  assert.equal(
    friendsSurfaceIsEmpty(
      friendsSurface({ ...NO_FRIENDS, incoming: [surfaceEntry("asker")] }),
    ),
    false,
  );
  assert.equal(
    friendsSurfaceIsEmpty(
      friendsSurface({ ...NO_FRIENDS, outgoing: [surfaceEntry("asked")] }),
    ),
    false,
  );
});

// --------------------------------------------- reaching one specific person

test("a profile offers a friendship only where one can exist", () => {
  const me = { userId: "me", isAnonymous: false };
  const them = { userId: "them", isAnonymous: false };
  assert.equal(profileFriendActionFor(them, NO_FRIENDS, me), "add");
  // Nobody is their own friend, and a guest on either side cannot hold one.
  assert.equal(profileFriendActionFor(me, NO_FRIENDS, me), "none");
  assert.equal(
    profileFriendActionFor({ userId: "them", isAnonymous: true }, NO_FRIENDS, me),
    "none",
  );
  assert.equal(
    profileFriendActionFor(them, NO_FRIENDS, { userId: "me", isAnonymous: true }),
    "none",
  );
  // Signed out, and a profile that has not loaded yet.
  assert.equal(profileFriendActionFor(them, NO_FRIENDS, null), "none");
  assert.equal(profileFriendActionFor(null, NO_FRIENDS, me), "none");
});

test("a profile reflects which way an existing request points", () => {
  const me = { userId: "me", isAnonymous: false };
  const them = { userId: "them", isAnonymous: false };
  const of = (key) => profileFriendActionFor(them, { ...NO_FRIENDS, [key]: [entry("them")] }, me);
  assert.equal(of("friends"), "friends");
  assert.equal(of("incoming"), "accept");
  assert.equal(of("outgoing"), "sent");
});

test("recent players are parsed and a malformed row is dropped, not faked", () => {
  const parsed = parseRecentPlayers({
    players: [
      { userId: "a", displayName: "Ada", nameColor: "#4f9", avatarUrl: null, lastPlayedAt: "2026-09-01T00:00:00Z" },
      { userId: "", displayName: "Nameless" },
      { displayName: "No id" },
      "not an object",
    ],
  });
  assert.deepEqual(parsed.map((row) => row.userId), ["a"]);
  assert.equal(parsed[0].nameColor, "#4f9");
  assert.deepEqual(parseRecentPlayers(null), []);
  assert.deepEqual(parseRecentPlayers({ players: "nope" }), []);
});

test("a suggestion is dropped once it is on one of the lists, but a refusal is not", () => {
  const players = [
    { userId: "friend", displayName: "F", nameColor: null, avatarUrl: null, lastPlayedAt: "" },
    { userId: "asked-me", displayName: "I", nameColor: null, avatarUrl: null, lastPlayedAt: "" },
    { userId: "i-asked", displayName: "O", nameColor: null, avatarUrl: null, lastPlayedAt: "" },
    { userId: "declined-me", displayName: "D", nameColor: null, avatarUrl: null, lastPlayedAt: "" },
  ];
  const left = addableRecentPlayers(players, {
    friends: [entry("friend")],
    incoming: [entry("asked-me")],
    outgoing: [entry("i-asked")],
  });
  // The refusal stays: dropping it would make the absence readable, which is
  // exactly what R-FRIEND-04 refuses to disclose. Its button quietly does
  // nothing, which is what a decline is meant to feel like.
  assert.deepEqual(left.map((row) => row.userId), ["declined-me"]);
});

// ------------------------------------------------ what moved since last time

test("a request arriving and one being answered are told apart", () => {
  const before = { ...NO_FRIENDS, outgoing: [entry("asked-them")] };
  const after = {
    friends: [entry("asked-them")],
    incoming: [entry("new-asker")],
    outgoing: [],
  };
  const changes = friendListChanges(before, after);
  assert.deepEqual(changes.arrived.map((row) => row.userId), ["new-asker"]);
  assert.deepEqual(changes.accepted.map((row) => row.userId), ["asked-them"]);
});

test("a request that stopped being pending is never reported", () => {
  // What a decline looks like from the sender's side. The row going away is
  // legible; naming it would go further than R-FRIEND-05 allows.
  const changes = friendListChanges(
    { ...NO_FRIENDS, outgoing: [entry("they-said-no")] },
    NO_FRIENDS,
  );
  assert.deepEqual(changes, { arrived: [], accepted: [] });
});

test("answering a request yourself is not news", () => {
  // Accepting somebody who asked you puts them in `friends` for the first
  // time too, and being told what you just did is noise.
  const changes = friendListChanges(
    { ...NO_FRIENDS, incoming: [entry("asked-me")] },
    { ...NO_FRIENDS, friends: [entry("asked-me")] },
  );
  assert.deepEqual(changes.accepted, []);
  assert.deepEqual(changes.arrived, []);
});

test("a request still waiting is not re-announced", () => {
  const lists = { ...NO_FRIENDS, incoming: [entry("patient")] };
  assert.deepEqual(friendListChanges(lists, lists), { arrived: [], accepted: [] });
});

test("the badge counts only what is waiting for an answer", () => {
  assert.equal(waitingRequestCount(NO_FRIENDS), 0);
  assert.equal(
    waitingRequestCount({
      friends: [entry("a"), entry("b")],
      incoming: [entry("c")],
      outgoing: [entry("d"), entry("e")],
    }),
    1,
  );
});
