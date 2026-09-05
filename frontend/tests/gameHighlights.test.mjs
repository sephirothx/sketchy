import assert from "node:assert/strict";
import test from "node:test";

import {
  presentHighlight,
  presentHighlights,
} from "../src/lib/gameHighlights.ts";

test("the hardest prompt reports the share that got it, not a ratio", () => {
  const presented = presentHighlight({
    kind: "hardest_prompt",
    prompt: "roller coaster",
    correctGuessCount: 1,
    totalGuesserCount: 4,
  });
  assert.equal(presented.label, "Hardest prompt");
  assert.equal(presented.value, "1 of 4 guessed it");
  assert.equal(presented.prompt, "roller coaster");
  assert.equal(presented.name, undefined);
});

test("guess times render to one decimal", () => {
  assert.equal(
    presentHighlight({
      kind: "fastest_guess",
      prompt: "cat",
      seconds: 3.24,
      nickname: "Ana",
    }).value,
    "3.2s",
  );
  // A whole number still shows its decimal, so the column does not ragged.
  assert.equal(
    presentHighlight({
      kind: "quickest_average",
      seconds: 8,
      nickname: "Bo",
    }).value,
    "8.0s",
  );
});

test("a drawer's ratio renders as a percentage", () => {
  assert.equal(
    presentHighlight({
      kind: "best_drawer",
      guessRatio: 0.8571,
      nickname: "Cy",
    }).value,
    "86% guessed",
  );
  assert.equal(
    presentHighlight({ kind: "best_drawer", guessRatio: 1, nickname: "Cy" }).value,
    "100% guessed",
  );
});

test("highlights that belong to a player carry the name to render", () => {
  const presented = presentHighlight({
    kind: "fastest_guess",
    prompt: "cat",
    seconds: 1.5,
    nickname: "Ana",
    nameColor: "#a761e5",
    isAnonymous: false,
  });
  assert.equal(presented.name?.nickname, "Ana");
  assert.equal(presented.name?.nameColor, "#a761e5");
  assert.equal(presented.name?.isAnonymous, false);
});

test("an absent or empty highlight list presents nothing", () => {
  assert.deepEqual(presentHighlights(undefined), []);
  assert.deepEqual(presentHighlights([]), []);
});

test("every highlight presents a label and a value", () => {
  const all = [
    { kind: "hardest_prompt", prompt: "x", correctGuessCount: 0, totalGuesserCount: 3 },
    { kind: "fastest_guess", prompt: "x", seconds: 2, nickname: "Ana" },
    { kind: "best_drawer", guessRatio: 0.5, nickname: "Bo" },
    { kind: "quickest_average", seconds: 4, nickname: "Cy" },
    {
      kind: "most_reacted_drawing",
      prompt: "x",
      reactionCount: 2,
      drawingIndex: 1,
      turnId: "t",
      nickname: "Di",
    },
  ];
  for (const presented of presentHighlights(all)) {
    assert.ok(presented.label.length > 0, `${presented.kind} has no label`);
    assert.ok(presented.value.length > 0, `${presented.kind} has no value`);
  }
});

test("the most reacted drawing counts reactions and remembers where it is", () => {
  const presented = presentHighlight({
    kind: "most_reacted_drawing",
    prompt: "lighthouse",
    reactionCount: 3,
    drawingIndex: 2,
    turnId: "turn-3",
    nickname: "Ana",
  });
  assert.equal(presented.label, "Most reacted drawing");
  assert.equal(presented.value, "3 reactions");
  assert.equal(presented.prompt, "lighthouse");
  assert.equal(presented.name?.nickname, "Ana");
  assert.equal(presented.drawingIndex, 2);
  assert.equal(
    presentHighlight({
      kind: "most_reacted_drawing",
      prompt: "kite",
      reactionCount: 1,
      drawingIndex: 0,
      turnId: "turn-1",
      nickname: "Bo",
    }).value,
    "1 reaction",
  );
});
