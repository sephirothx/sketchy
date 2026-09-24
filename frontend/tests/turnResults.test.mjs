import assert from "node:assert/strict";
import test from "node:test";

import { isTurnAlreadyShown } from "../src/lib/turnResults.ts";

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

test("without turn ids, the prompt and drawer decide", () => {
  const legacy = ended({ turnId: undefined });
  assert.equal(isTurnAlreadyShown({ phase: "turn_results", lastTurnResult: legacy }, legacy), true);
  assert.equal(
    isTurnAlreadyShown(
      { phase: "turn_results", lastTurnResult: legacy },
      ended({ turnId: undefined, drawerId: "someone else" }),
    ),
    false,
  );
});
