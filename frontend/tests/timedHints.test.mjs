import assert from "node:assert/strict";
import test from "node:test";

import { useGameStore } from "../src/store/gameStore.ts";

// A timed hint is emitted per seat (#883), so the turn can end between two of
// them. The server stops as soon as it notices; a hint already on the wire is
// the client's to drop, and it names its turn so the client can.

function drawing(turnId, maskedPrompt = "_ _ _") {
  const store = useGameStore.getState();
  store.reset();
  store.startDrawing({
    drawerId: "p1", maskedPrompt, roundNumber: 1, totalRounds: 3, seconds: 80,
    hintCost: 10, letterPrices: {}, hintSpend: 0, maxHintSpend: 100, turnId,
  });
  return store;
}

test("a hint for the turn being drawn is applied", () => {
  const store = drawing("turn-1");
  store.setHintRevealed({ maskedPrompt: "c _ t", turnId: "turn-1" });
  assert.equal(useGameStore.getState().maskedPrompt, "c _ t");
});

test("a hint for another turn is dropped", () => {
  const store = drawing("turn-1");
  store.setHintRevealed({ maskedPrompt: "stale", turnId: "turn-0" });
  assert.equal(useGameStore.getState().maskedPrompt, "_ _ _");
});

test("a hint that lands after the turn ended never re-masks the prompt", () => {
  const store = drawing("turn-1");
  store.endTurn({ prompt: "cat", scores: [], turnId: "turn-1" });
  store.setHintRevealed({ maskedPrompt: "c _ t", turnId: "turn-1" });
  assert.equal(useGameStore.getState().lastTurnResult.prompt, "cat");
  assert.equal(useGameStore.getState().maskedPrompt, "_ _ _", "the revealed prompt stood");
});

test("a hint that lands while the next drawer is choosing is dropped", () => {
  // An abandoned turn - the drawer left - goes straight to the next turn's
  // preamble, never through turn_results.
  const store = drawing("turn-1");
  store.startChoosing({ drawerId: "p2", roundNumber: 1, totalRounds: 3, seconds: 15 });
  const choosing = useGameStore.getState().maskedPrompt;
  store.setHintRevealed({ maskedPrompt: "stale", turnId: "turn-1" });
  assert.equal(
    useGameStore.getState().maskedPrompt, choosing, "the last turn's blanks stayed off"
  );
});

test("a bought hint names no turn and always lands: it answers what was just pressed", () => {
  const store = drawing("turn-1");
  store.setHintRevealed({ maskedPrompt: "c a t", hintCost: 20, hintSpend: 10 });
  assert.equal(useGameStore.getState().maskedPrompt, "c a t");
  assert.equal(useGameStore.getState().nextHintCost, 20);
});
