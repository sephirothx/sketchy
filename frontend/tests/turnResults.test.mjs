import assert from "node:assert/strict";
import test from "node:test";

import { isTurnAlreadyShown } from "../src/lib/turnResults.ts";
import { useGameStore } from "../src/store/gameStore.ts";

// #1018: a rebind during a turn's results re-sends turn_ended, and each one
// added another "The prompt was …" line to the chat.

const ended = (overrides = {}) => ({
  prompt: "otter",
  turnId: "turn-1",
  drawerId: "drawer",
  drawerBonus: 0,
  guesses: [],
  ...overrides,
});

test("the first turn_ended of a turn is not a repeat", () => {
  assert.equal(isTurnAlreadyShown({ phase: "drawing", lastTurnResult: null }, ended()), false);
  assert.equal(
    isTurnAlreadyShown({ phase: "drawing", lastTurnResult: ended({ turnId: "turn-0" }) }, ended()),
    false,
  );
});

test("the same turn re-sent during its results is a repeat", () => {
  assert.equal(isTurnAlreadyShown({ phase: "turn_results", lastTurnResult: ended() }, ended()), true);
});

test("the next turn's results are not a repeat, even over the last one's screen", () => {
  assert.equal(
    isTurnAlreadyShown(
      { phase: "turn_results", lastTurnResult: ended() },
      ended({ turnId: "turn-2", prompt: "otter" }),
    ),
    false,
  );
});

test("a turn_ended without a turn id is never taken for a repeat", () => {
  const legacy = ended({ turnId: undefined });
  assert.equal(isTurnAlreadyShown({ phase: "turn_results", lastTurnResult: legacy }, legacy), false);
});

test("the store says the prompt once however many times the turn is re-sent", () => {
  const store = useGameStore.getState();
  store.resetGame?.();
  useGameStore.setState({ messages: [], phase: "drawing", lastTurnResult: null, players: [] });
  let line = 0;
  const say = () => ({ id: `line-${++line}`, nickname: "", text: "The prompt was otter", correct: false, system: true });

  useGameStore.getState().applyTurnEnded(ended({ scores: [] }), say);
  useGameStore.getState().applyTurnEnded(ended({ scores: [] }), say);
  useGameStore.getState().applyTurnEnded(ended({ scores: [] }), say);
  assert.equal(useGameStore.getState().messages.length, 1);
  assert.equal(useGameStore.getState().phase, "turn_results");

  useGameStore.getState().applyTurnEnded(ended({ turnId: "turn-2", scores: [] }), say);
  assert.equal(useGameStore.getState().messages.length, 2, "the next turn is said too");
});
