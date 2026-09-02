import assert from "node:assert/strict";
import test from "node:test";

import {
  NO_ROOMS,
  applyRoomsDelta,
  applyRoomsSnapshot,
  markRoomsStale,
} from "../src/lib/lobbyRooms.ts";

const room = (id, extra = {}) => ({ id, name: `Room ${id}`, playerCount: 2, ...extra });

test("a client with no snapshot yet can tell empty from not-told-yet", () => {
  assert.equal(NO_ROOMS.loaded, false);
  assert.deepEqual(NO_ROOMS.rooms, []);

  const told = applyRoomsSnapshot(NO_ROOMS, [], 7);
  assert.equal(told.loaded, true);
  assert.deepEqual(told.rooms, []);
  // The distinction is the whole reason `loaded` exists: without it a server
  // with no public rooms is indistinguishable from one that never answered,
  // and the lobby would sit on a spinner forever.
});

test("a snapshot replaces whatever was held", () => {
  const state = applyRoomsSnapshot(NO_ROOMS, [room("a"), room("b")], 3);
  const next = applyRoomsSnapshot(state, [room("c")], 9);
  assert.deepEqual(next.rooms.map((r) => r.id), ["c"]);
  assert.equal(next.revision, 9);
  assert.notEqual(state.revision, next.revision);
});

test("a snapshot with no usable revision is refused whole", () => {
  for (const revision of [undefined, null, "3", -1, 1.5]) {
    assert.deepEqual(applyRoomsSnapshot(NO_ROOMS, [room("a")], revision), NO_ROOMS);
  }
});

test("a delta opens, changes and closes", () => {
  const state = applyRoomsSnapshot(NO_ROOMS, [room("a"), room("b")], 1);
  const next = applyRoomsDelta(state, {
    revision: 2,
    opened: [room("c")],
    changed: [room("a", { playerCount: 5 })],
    closed: ["b"],
  });
  assert.deepEqual(next.rooms.map((r) => r.id).sort(), ["a", "c"]);
  assert.equal(next.rooms.find((r) => r.id === "a").playerCount, 5);
  assert.equal(next.revision, 2);
  assert.equal(next.needsResync, false);
});

test("a delta the client already has is ignored", () => {
  const state = applyRoomsSnapshot(NO_ROOMS, [room("a")], 5);
  for (const revision of [5, 4, 1]) {
    const next = applyRoomsDelta(state, { revision, closed: ["a"] });
    assert.equal(next, state, `revision ${revision}`);
  }
});

test("a gap asks for a resync rather than patching around it", () => {
  const state = applyRoomsSnapshot(NO_ROOMS, [room("a")], 1);
  const next = applyRoomsDelta(state, { revision: 4, closed: ["a"] });
  assert.equal(next.needsResync, true);
  // The list it already had is left intact and still drawable. Only the
  // hook reads `needsResync`, and what it does is re-subscribe.
  assert.deepEqual(next.rooms.map((r) => r.id), ["a"]);
  assert.equal(next.revision, 1);
});

test("closing a room nobody has is a no-op, not a hole", () => {
  const state = applyRoomsSnapshot(NO_ROOMS, [room("a")], 1);
  const next = applyRoomsDelta(state, { revision: 2, closed: ["nope"] });
  assert.deepEqual(next.rooms.map((r) => r.id), ["a"]);
  assert.equal(next.revision, 2);
});

test("a room this build cannot place is dropped, not rendered blank", () => {
  const next = applyRoomsSnapshot(NO_ROOMS, [room("a"), { name: "no id" }, null, 7], 1);
  assert.deepEqual(next.rooms.map((r) => r.id), ["a"]);
});

test("a delta that is not a delta leaves the list alone", () => {
  const state = applyRoomsSnapshot(NO_ROOMS, [room("a")], 1);
  for (const payload of [undefined, null, "2", 2, { revision: "2" }, {}]) {
    assert.equal(applyRoomsDelta(state, payload), state, String(payload));
  }
});

test("a sequence of deltas agrees with the snapshot it should equal", () => {
  // The #493 contract, on the client side: patching must not drift from
  // replacing. A store that disagrees here is one that looks right until
  // somebody reloads.
  let patched = applyRoomsSnapshot(NO_ROOMS, [room("a"), room("b")], 1);
  patched = applyRoomsDelta(patched, { revision: 2, opened: [room("c")] });
  patched = applyRoomsDelta(patched, { revision: 3, closed: ["a"] });
  patched = applyRoomsDelta(patched, {
    revision: 4,
    changed: [room("b", { playerCount: 8 })],
  });

  const replaced = applyRoomsSnapshot(NO_ROOMS, [room("b", { playerCount: 8 }), room("c")], 4);
  assert.deepEqual(
    [...patched.rooms].sort((x, y) => x.id.localeCompare(y.id)),
    [...replaced.rooms].sort((x, y) => x.id.localeCompare(y.id)),
  );
  assert.equal(patched.revision, replaced.revision);
});


test("a dropped socket keeps the rooms and abandons the sequence", () => {
  const state = applyRoomsSnapshot(NO_ROOMS, [room("a"), room("b")], 12);
  const stale = markRoomsStale(state);
  // Still drawable: these rooms were true a moment ago and are public. A poll
  // would have gone on showing them for up to four seconds.
  assert.deepEqual(stale.rooms.map((r) => r.id), ["a", "b"]);
  assert.equal(stale.loaded, true);
  assert.equal(stale.stale, true);
  assert.equal(stale.revision, 0);
});

test("a stale list is not patched, only replaced", () => {
  const stale = markRoomsStale(applyRoomsSnapshot(NO_ROOMS, [room("a")], 12));
  // Revision 1 is `stale.revision + 1`, so without the stale check this delta
  // would apply cleanly and wrongly - the new server's sequence has nothing to
  // do with the list this client is holding.
  assert.equal(applyRoomsDelta(stale, { revision: 1, closed: ["a"] }), stale);

  const fresh = applyRoomsSnapshot(NO_ROOMS, [room("c")], 1);
  assert.equal(fresh.stale, false);
  assert.deepEqual(applyRoomsDelta(fresh, { revision: 2, opened: [room("d")] })
    .rooms.map((r) => r.id).sort(), ["c", "d"]);
});

test("going stale before anything arrived stays not-told-yet", () => {
  // Otherwise a socket that drops before its first acknowledgement would leave
  // the lobby claiming, with an empty list, that there are no rooms.
  assert.equal(markRoomsStale(NO_ROOMS), NO_ROOMS);
});


test("a delta before the baseline is refused, not patched onto nothing", () => {
  // The server joins the channel before it builds the acknowledgement, so the
  // first delta can beat the list it applies to. Patching an empty list would
  // leave the lobby showing only the rooms that happened to move, with
  // `loaded` claiming that was all of them.
  const early = applyRoomsDelta(NO_ROOMS, { revision: 1, opened: [room("a")] });
  assert.equal(early, NO_ROOMS);
  assert.equal(early.loaded, false);

  // And the acknowledgement, arriving second, is still the whole truth.
  const settled = applyRoomsSnapshot(early, [room("a"), room("b")], 1);
  assert.deepEqual(settled.rooms.map((r) => r.id), ["a", "b"]);
});

test("a snapshot never moves the list backwards", () => {
  const state = applyRoomsSnapshot(NO_ROOMS, [room("a")], 9);
  // An acknowledgement built before a delta this client already applied.
  assert.equal(applyRoomsSnapshot(state, [room("z")], 4), state);
  // Its own revision again is not backwards, and replacing is harmless.
  assert.deepEqual(
    applyRoomsSnapshot(state, [room("z")], 9).rooms.map((r) => r.id),
    ["z"],
  );
});

test("a stale list accepts any snapshot, however it is numbered", () => {
  // Its revision is 0 and means nothing; the new connection's numbering is
  // the only one there is.
  const stale = markRoomsStale(applyRoomsSnapshot(NO_ROOMS, [room("a")], 40));
  const fresh = applyRoomsSnapshot(stale, [room("b")], 2);
  assert.deepEqual(fresh.rooms.map((r) => r.id), ["b"]);
  assert.equal(fresh.stale, false);
  assert.equal(fresh.revision, 2);
});
