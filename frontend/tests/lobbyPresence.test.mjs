import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  EMPTY_PRESENCE,
  applyDelta,
  applySnapshot,
  comparePlayers,
  filterPlayers,
  parsePlayer,
  presenceSummary,
} from "../src/lib/lobbyPresence.ts";

const FIXTURE = JSON.parse(
  readFileSync(new URL("../../fixtures/lobby_presence_v1.json", import.meta.url)),
);

const player = (userId, displayName, extra = {}) => ({
  userId,
  displayName,
  nameColor: "#4f9",
  isAnonymous: false,
  status: "lobby",
  ...extra,
});

const snapshot = (revision, players, onlineCount = players.length) =>
  applySnapshot({ revision, players, onlineCount });

test("the sort matches the one the server pins", () => {
  // The same fixture backend/tests/test_presence.py reads, so a comparator
  // changed on one side alone fails on the other.
  const ordered = [...FIXTURE.entries].sort(comparePlayers).map((p) => p.userId);
  assert.deepEqual(ordered, FIXTURE.sortedUserIds);
});

test("a snapshot replaces the store wholesale", () => {
  const first = snapshot(4, [player("u1", "Ada")], 9);
  const second = applySnapshot({
    revision: 5,
    players: [player("u2", "Bob")],
    onlineCount: 1,
  });
  assert.deepEqual(first.players.map((p) => p.userId), ["u1"]);
  assert.deepEqual(second.players.map((p) => p.userId), ["u2"]);
  assert.equal(second.revision, 5);
  assert.equal(second.onlineCount, 1);
});

test("a delta joins, changes and leaves, then re-sorts", () => {
  const state = snapshot(1, [player("u1", "bob"), player("u2", "zoe")]);
  const next = applyDelta(state, {
    revision: 2,
    joined: [player("u3", "ada")],
    changed: [player("u2", "zoe", { status: "playing" })],
    left: ["u1"],
    onlineCount: 2,
  });
  assert.deepEqual(next.players.map((p) => p.displayName), ["ada", "zoe"]);
  assert.equal(next.players[1].status, "playing");
  assert.equal(next.revision, 2);
});

test("a revision gap asks for a resync instead of patching around it", () => {
  const state = snapshot(1, [player("u1", "Ada")]);
  const next = applyDelta(state, { revision: 3, joined: [player("u2", "Bob")] });
  assert.equal(next.needsResync, true);
  // The store is left exactly as it was: it is about to be replaced, and a
  // half-applied list is worse than a stale one.
  assert.deepEqual(next.players.map((p) => p.userId), ["u1"]);
  assert.equal(next.revision, 1);
});

test("a delta already seen is ignored", () => {
  const state = snapshot(4, [player("u1", "Ada")]);
  for (const revision of [4, 3, 0]) {
    const next = applyDelta(state, { revision, left: ["u1"] });
    assert.equal(next.needsResync, false);
    assert.deepEqual(next.players.map((p) => p.userId), ["u1"]);
  }
});

test("applying a delta twice changes nothing the second time", () => {
  // What lets the watch_lobby acknowledgement carry a fresher list than the
  // channel is on without the next delta double-counting anything.
  const state = snapshot(1, [player("u1", "Ada")]);
  const delta = {
    revision: 2,
    joined: [player("u2", "Bob")],
    left: ["u1"],
    onlineCount: 1,
  };
  const once = applyDelta(state, delta);
  const twice = applyDelta(once, { ...delta, revision: 3 });
  assert.deepEqual(twice.players, once.players);
  assert.equal(twice.onlineCount, once.onlineCount);
});

test("leaving somebody who was never there is not an error", () => {
  const state = snapshot(1, [player("u1", "Ada")]);
  const next = applyDelta(state, { revision: 2, left: ["ghost"], onlineCount: 1 });
  assert.deepEqual(next.players.map((p) => p.userId), ["u1"]);
});

test("a row this build cannot read is dropped rather than rendered", () => {
  assert.equal(parsePlayer({ userId: "u1", displayName: "Ada" }), null);
  assert.equal(parsePlayer({ userId: "", displayName: "Ada", status: "lobby" }), null);
  assert.equal(parsePlayer({ displayName: "Ada", status: "lobby" }), null);
  const state = applySnapshot({
    revision: 1,
    players: [player("u1", "Ada"), { userId: "u2" }],
    onlineCount: 2,
  });
  assert.deepEqual(state.players.map((p) => p.userId), ["u1"]);
  // Still counted: the total is how many are online, not how many rendered.
  assert.equal(state.onlineCount, 2);
});

test("a malformed message leaves the store alone", () => {
  const state = snapshot(1, [player("u1", "Ada")]);
  for (const bad of [null, undefined, 7, "nope", {}, { revision: -1 }]) {
    assert.deepEqual(applyDelta(state, bad).players, state.players);
  }
  assert.deepEqual(applySnapshot(null), EMPTY_PRESENCE);
});

test("the summary says how many were left out", () => {
  assert.equal(presenceSummary(snapshot(1, [], 0)), "0 online");
  assert.equal(presenceSummary(snapshot(1, [player("u1", "Ada")], 1)), "1 online");
  assert.equal(
    presenceSummary(snapshot(1, [player("u1", "Ada")], 412)),
    "Showing 1 of 412",
  );
});

test("the filter matches anywhere in a name, case-insensitively", () => {
  const players = [player("u1", "Ada"), player("u2", "badger"), player("u3", "zoe")];
  assert.deepEqual(filterPlayers(players, "AD").map((p) => p.userId), ["u1", "u2"]);
  assert.deepEqual(filterPlayers(players, "  ").map((p) => p.userId), ["u1", "u2", "u3"]);
  assert.deepEqual(filterPlayers(players, "nobody"), []);
});
