import assert from "node:assert/strict";
import test from "node:test";

import { placeNotices } from "../src/lib/appNotices.ts";

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
