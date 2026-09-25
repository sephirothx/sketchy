import assert from "node:assert/strict";
import test from "node:test";

import { gameLength, gameMinutes, changedRoomRules } from "../src/lib/roomCardFacts.ts";

const standard = {
  id: "r1",
  code: "ABC123",
  name: "The Sketchy Art Class",
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
};

test("a game's length matches the Create page's estimate for the same room", () => {
  // 8 players x 3 rounds x (90s + 24s) = 2736s, about 46 minutes.
  assert.equal(gameMinutes(standard, 8), 46);
  assert.equal(gameMinutes({ rounds: 1, drawingSeconds: 15 }, 2), 1);
});

test("the range runs from the seats taken, never fewer than two, to a full room", () => {
  assert.deepEqual(gameLength(standard), { low: 11, high: 46 });
  assert.deepEqual(gameLength({ ...standard, playerCount: 5 }), { low: 29, high: 46 });
  assert.deepEqual(gameLength({ ...standard, playerCount: 8 }), { low: 46, high: 46 });
});

test("a room on standard settings has no room rules to show", () => {
  assert.deepEqual(changedRoomRules(standard), []);
});

test("only the settings that differ from a new room's are named, in a fixed order", () => {
  assert.deepEqual(
    changedRoomRules({
      ...standard,
      spectatorsSeePrompt: true,
      customPromptCount: 40,
      colorMode: "black_and_white",
      allowedTools: ["brush"],
      hintMode: "wheel",
      scoringMode: "pressure",
    }),
    [
      "Pressure scoring",
      "Wheel of Fortune",
      "Brush only, black and white",
      "40 custom prompts plus defaults",
      "Spectators can see the prompt",
    ],
  );
  assert.deepEqual(changedRoomRules({ ...standard, scoringMode: "none", hideMaskedPrompt: true }), [
    "No scoring",
    "Letter tiles hidden",
  ]);
  assert.deepEqual(changedRoomRules({ ...standard, customPromptCount: 1, customPromptsOnly: true }), [
    "1 custom prompt only",
  ]);
});

test("a room's six facts come in one order, and only the choices are marked changed", async () => {
  const { roomFacts, otherRoomRules } = await import("../src/lib/roomCardFacts.ts");
  const facts = roomFacts({
    ...standard,
    playerCount: 2,
    scoringMode: "pressure",
    customPromptCount: 40,
    promptListSlugs: ["en-standard"],
  });
  assert.deepEqual(facts.map((fact) => fact.key), ["players", "rounds", "drawing-time", "scoring", "hints", "prompts"]);
  assert.deepEqual(
    facts.map((fact) => [fact.value, fact.changed]),
    [
      ["2 of 8", false],
      ["3", false],
      ["90s", false],
      ["Pressure", true],
      ["Timed hints", false],
      ["English · 40 custom", true],
    ],
  );
  assert.deepEqual(otherRoomRules(standard), []);
  assert.deepEqual(
    otherRoomRules({ ...standard, allowedTools: ["brush"], spectatorsSeePrompt: true }),
    ["Brush only", "Spectators see the prompt"],
  );
});

test("a room on several lists but no custom prompts says how many lists", async () => {
  const { roomFacts } = await import("../src/lib/roomCardFacts.ts");
  const prompts = roomFacts({ ...standard, promptListSlugs: ["a", "b"] }).find((fact) => fact.key === "prompts");
  assert.deepEqual([prompts.value, prompts.changed], ["English · 2 lists", true]);
});

test("a room on a single list other than its language's Standard one is marked, not passed off as the default", async () => {
  const { roomFacts } = await import("../src/lib/roomCardFacts.ts");
  const promptsOf = (slugs) => roomFacts({ ...standard, promptListSlugs: slugs }).find((fact) => fact.key === "prompts");
  const standardOnly = promptsOf(["english_standard"]);
  assert.deepEqual([standardOnly.value, standardOnly.changed], ["English", false]);
  const community = promptsOf(["community-0f3a"]);
  assert.deepEqual([community.value, community.changed], ["English · 1 list", true]);
  const extended = promptsOf(["english_extended"]);
  assert.deepEqual([extended.value, extended.changed], ["English · 1 list", true]);
});
