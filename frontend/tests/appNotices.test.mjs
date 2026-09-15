import assert from "node:assert/strict";
import test from "node:test";

import { placeNotices, roomStage } from "../src/lib/appNotices.ts";
import { useServerNoticesStore } from "../src/store/serverNoticesStore.ts";

const QUIET = {
  inRoom: false,
  updateRequired: false,
  serverFull: false,
  paused: false,
  draining: false,
  restarted: false,
  connection: "connected",
};

test("nothing wrong, nothing shown", () => {
  assert.deepEqual(placeNotices(QUIET), { banners: [], chips: [] });
  assert.deepEqual(placeNotices({ ...QUIET, inRoom: true }), { banners: [], chips: [] });
});

test("in a room, a drain and a dropped connection are header chips, not banners", () => {
  // The banners sat on top of the phone's playing shell and took the header's
  // taps (#797); these two are the notices that happen mid-game.
  const facts = { ...QUIET, inRoom: true, draining: true, connection: "reconnecting" };
  assert.deepEqual(placeNotices(facts), { banners: [], chips: ["drain", "connection"] });
});

test("outside a room the same two are banners, in the order they always stacked", () => {
  const facts = { ...QUIET, draining: true, connection: "offline" };
  assert.deepEqual(placeNotices(facts), { banners: ["drain", "connection"], chips: [] });
});

test("an out-of-date tab keeps its banner in a room, and is not also told it is reconnecting", () => {
  // Nothing underneath works, and it has stopped reconnecting on purpose.
  const facts = { ...QUIET, inRoom: true, updateRequired: true, connection: "reconnecting" };
  assert.deepEqual(placeNotices(facts), { banners: ["update-required"], chips: [] });
});

test("a pause is not a game's business, and a drain outranks it anywhere", () => {
  assert.deepEqual(placeNotices({ ...QUIET, paused: true }).banners, ["paused"]);
  assert.deepEqual(placeNotices({ ...QUIET, paused: true, inRoom: true }), { banners: [], chips: [] });
  assert.deepEqual(placeNotices({ ...QUIET, paused: true, draining: true }).banners, ["drain"]);
});

test("server full yields to update required, and restarted stays a banner", () => {
  assert.deepEqual(
    placeNotices({ ...QUIET, serverFull: true, updateRequired: true, restarted: true }).banners,
    ["update-required", "restarted"],
  );
});

test("inside a room the restart is the end screen's to say, not a banner's", () => {
  assert.deepEqual(placeNotices({ ...QUIET, inRoom: true, restarted: true }).banners, []);
});

const LIVE = {
  code: "ABC123",
  connection: "connected",
  pauseDue: false,
  lostDuringDrain: false,
  updateRequired: false,
  roomEnded: null,
};

test("a blip pauses nothing; trouble that outlasts the delay pauses the stage", () => {
  // #823: the room went on looking alive under a lone chip - the ring
  // counting, the guess field taking input that went nowhere.
  assert.deepEqual(roomStage(LIVE), { kind: "live" });
  assert.deepEqual(roomStage({ ...LIVE, connection: "reconnecting" }), { kind: "live" });
  assert.deepEqual(
    roomStage({ ...LIVE, connection: "reconnecting", pauseDue: true }),
    { kind: "paused", cause: "reconnecting" },
  );
  assert.deepEqual(
    roomStage({ ...LIVE, connection: "offline", pauseDue: true }),
    { kind: "paused", cause: "offline" },
  );
});

test("a connection lost during a drain says the server is updating", () => {
  assert.deepEqual(
    roomStage({ ...LIVE, connection: "reconnecting", pauseDue: true, lostDuringDrain: true }),
    { kind: "paused", cause: "server-update" },
  );
});

test("a failed rebind pauses with its own cause, and an out-of-date tab is left to its banner", () => {
  assert.deepEqual(
    roomStage({ ...LIVE, connection: "failed", pauseDue: true }),
    { kind: "paused", cause: "failed" },
  );
  assert.deepEqual(
    roomStage({ ...LIVE, connection: "reconnecting", pauseDue: true, updateRequired: true }),
    { kind: "live" },
  );
});

test("a room the server says is gone is ended - that room, and no other", () => {
  const roomEnded = { code: "ABC123", reason: "room-closed" };
  assert.deepEqual(roomStage({ ...LIVE, roomEnded }), { kind: "ended", reason: "room-closed" });
  assert.deepEqual(roomStage({ ...LIVE, code: "XYZ789", roomEnded }), { kind: "live" });
  assert.deepEqual(roomStage({ ...LIVE, code: null, roomEnded }), { kind: "live" });
});

test("the end reason is an update when a drain was seen before the loss", () => {
  const store = useServerNoticesStore;
  store.getState().set({ lostDuringDrain: true, restarted: false, roomEnded: null });
  store.getState().markRoomEnded("ABC123");
  assert.deepEqual(store.getState().roomEnded, { code: "ABC123", reason: "server-update" });
  assert.equal(store.getState().lostDuringDrain, false);

  // The banner is spent by the end screen, and a crash - no drain - is a room
  // that closed.
  // Asked again, the first answer stands: the flags that named it are spent.
  store.getState().markRoomEnded("ABC123");
  assert.deepEqual(store.getState().roomEnded, { code: "ABC123", reason: "server-update" });

  store.getState().set({ restarted: true });
  store.getState().markRoomEnded("GHI000");
  assert.equal(store.getState().restarted, false);
  store.getState().markRoomEnded("DEF456");
  assert.deepEqual(store.getState().roomEnded, { code: "DEF456", reason: "room-closed" });
});
