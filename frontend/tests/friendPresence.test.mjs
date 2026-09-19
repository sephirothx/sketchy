import assert from "node:assert/strict";
import test from "node:test";

import {
  NO_FRIENDS_ONLINE,
  applyFriendPresence,
  invitableFriends,
  parseFriendsOnline,
  withOnlineFriends,
} from "../src/lib/friendPresence.ts";

const friend = (userId, displayName) => ({
  userId,
  displayName,
  nameColor: "#4f9",
  avatarUrl: null,
  isAnonymous: false,
  status: "accepted",
  requestedByMe: false,
  createdAt: "",
  respondedAt: null,
});
const lists = (...friends) => ({ friends, incoming: [], outgoing: [], announce: [] });

test("an answer is read row by row, and a row it cannot read is skipped", () => {
  assert.deepEqual(
    parseFriendsOnline({ ok: true, friends: [["a", "lobby"], ["b", "playing"], ["c", "away"], [1, "lobby"]] }),
    { a: "lobby", b: "playing" },
  );
  assert.equal(parseFriendsOnline({ ok: false }), NO_FRIENDS_ONLINE);
});

test("a push moves one friend, and a push that changes nothing returns the same map", () => {
  const online = { a: "lobby" };
  assert.deepEqual(applyFriendPresence(online, ["a", "playing"]), { a: "playing" });
  assert.deepEqual(applyFriendPresence(online, ["b", "lobby"]), { a: "lobby", b: "lobby" });
  assert.deepEqual(applyFriendPresence(online, ["a", null]), {});
  assert.equal(applyFriendPresence(online, ["a", "lobby"]), online);
  assert.equal(applyFriendPresence(online, ["z", null]), online);
  assert.equal(applyFriendPresence(online, "junk"), online);
});

test("only a friend in the lobby can be invited", () => {
  const l = lists(friend("a", "Ada"), friend("b", "Bob"), friend("c", "Cat"));
  assert.deepEqual(
    invitableFriends(l, { a: "lobby", b: "playing" }).map((f) => f.userId),
    ["a"],
  );
});

test("a friend the capped public list left out is still shown online (#878)", () => {
  const shown = [{ userId: "x", displayName: "Xan", nameColor: null, avatarUrl: null, isAnonymous: false, status: "lobby" }];
  const l = lists(friend("x", "Xan"), friend("z", "Zed"), friend("off", "Off"));
  const rows = withOnlineFriends(shown, l, { x: "lobby", z: "playing" });
  assert.deepEqual(rows.map((r) => [r.userId, r.status]), [["x", "lobby"], ["z", "playing"]]);
  assert.equal(withOnlineFriends(shown, l, { x: "lobby" }), shown);
});
