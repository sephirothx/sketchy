import assert from "node:assert/strict";
import test from "node:test";

import { quickPlayCandidates, quickPlayRoom } from "../src/lib/quickPlay.ts";

const room = (over) => ({
  id: over.id ?? over.name,
  code: "AAA111",
  name: over.name ?? "Room",
  isPublic: true,
  playerCount: 1,
  spectatorCount: 0,
  maxPlayers: 8,
  isFull: false,
  rounds: 3,
  customPromptCount: 0,
  customPromptsOnly: false,
  drawingSeconds: 90,
  hintMode: "checkpoints",
  scoringMode: "default",
  spectatorsSeePrompt: false,
  hideMaskedPrompt: false,
  allowedTools: ["brush", "fill", "shapes"],
  colorMode: "all",
  promptLanguage: "en",
  state: "waiting",
  ...over,
});

test("only a public room that is waiting with a seat free is worth trying", () => {
  const rooms = [
    room({ name: "playing", state: "playing" }),
    room({ name: "full", playerCount: 8 }),
    room({ name: "private", isPublic: false }),
    room({ name: "open" }),
  ];
  assert.deepEqual(quickPlayCandidates(rooms, "en").map((r) => r.name), ["open"]);
});

test("only rooms in your language, the one closest to a game first", () => {
  const rooms = [
    room({ name: "en-1", playerCount: 1 }),
    room({ name: "de-7", promptLanguage: "de", playerCount: 7 }),
    room({ name: "en-5", playerCount: 5 }),
    room({ name: "de-2", promptLanguage: "de", playerCount: 2 }),
  ];
  assert.deepEqual(quickPlayCandidates(rooms, "en").map((r) => r.name), ["en-5", "en-1"]);
  assert.deepEqual(quickPlayCandidates(rooms, "de").map((r) => r.name), ["de-7", "de-2"]);
  // A room in somebody else's language is never a candidate, however full.
  assert.deepEqual(quickPlayCandidates(rooms, "it"), []);
});

test("nothing open is not an error, it is an empty list", () => {
  assert.deepEqual(quickPlayCandidates([], "en"), []);
  assert.deepEqual(quickPlayCandidates([room({ name: "playing", state: "playing" })], "en"), []);
});

test("the room it opens is public, in your language, on the standard rules", () => {
  const setup = quickPlayRoom("de", false);
  assert.equal(setup.isPublic, true, "a private room would leave the next Quick play nothing to find");
  assert.equal(setup.promptLanguage, "de");
  assert.deepEqual(setup.promptListSlugs, [], "the server fills in that language's Standard list");
  assert.equal(setup.name, "", "the server names it");
  assert.equal(setup.rounds, 3);
  assert.equal(setup.maxPlayers, 8);
  assert.equal(setup.drawingSeconds, 90);
  assert.equal(setup.scoringMode, "default");
  assert.equal(setup.hintMode, "checkpoints");
  assert.equal(setup.customPrompts, "");
  assert.equal(quickPlayRoom("en", true).colorMode, "colorblind_safe");
  assert.equal(quickPlayRoom("en", false).colorMode, "all");
});

import { QUICK_PLAY_SKIPS, quickPlayReady, runQuickPlay } from "../src/lib/quickPlay.ts";
import { NO_ROOMS } from "../src/lib/lobbyRooms.ts";

test("a list that has not arrived, or has gone stale, is not one to decide from", () => {
  assert.equal(quickPlayReady(NO_ROOMS), false, "empty because nothing arrived is not empty");
  const live = { ...NO_ROOMS, loaded: true, revision: 3 };
  assert.equal(quickPlayReady(live), true);
  assert.equal(quickPlayReady({ ...live, stale: true }), false);
  assert.equal(quickPlayReady({ ...live, needsResync: true }), false);
});

test("only a refusal about that one room moves on to the next", () => {
  for (const code of ["room_full", "room_not_found", "room_ended", "room_not_open"]) {
    assert.ok(QUICK_PLAY_SKIPS.has(code), code);
  }
  for (const code of ["joining_too_fast", "seat_changing_too_fast", "database_busy", "name_in_use", "server_draining", "account_ended"]) {
    assert.ok(!QUICK_PLAY_SKIPS.has(code), `${code} would be the same for every room`);
  }
});

function refusal(errorCode) {
  return { ok: false, errorCode, error: errorCode };
}

test("the walk takes the first seat, and never opens a room once seated", async () => {
  const asked = [];
  const answer = await runQuickPlay(
    ["a", "b", "c"],
    async (room) => (asked.push(room), room === "b" ? { ok: true, code: "BBB222" } : refusal("room_full")),
    async () => assert.fail("opened a room with a seat to be had"),
  );
  assert.deepEqual(asked, ["a", "b"]);
  assert.equal(answer.code, "BBB222");
});

test("rooms that are gone are walked past, and a room is opened when all of them were", async () => {
  let opened = 0;
  const answer = await runQuickPlay(
    ["a", "b"],
    async (room) => refusal(room === "a" ? "room_not_open" : "room_full"),
    async () => (opened += 1, { ok: true, code: "NEW111" }),
  );
  assert.equal(opened, 1);
  assert.equal(answer.code, "NEW111");
});

test("a refusal about the player stops the walk: no second room, no room opened", async () => {
  const asked = [];
  const answer = await runQuickPlay(
    ["a", "b", "c"],
    async (room) => (asked.push(room), refusal("joining_too_fast")),
    async () => assert.fail("opened a room while the join allowance was spent"),
  );
  assert.deepEqual(asked, ["a"]);
  assert.equal(answer.errorCode, "joining_too_fast");
});

test("nothing to try is a room of your own", async () => {
  const answer = await runQuickPlay([], async () => assert.fail("joined nothing"), async () => ({ ok: true, code: "NEW222" }));
  assert.equal(answer.code, "NEW222");
});
