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
