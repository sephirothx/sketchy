import assert from "node:assert/strict";
import test from "node:test";

import { promptPickPayload } from "../src/lib/promptPick.ts";
import { useGameStore } from "../src/store/gameStore.ts";

test("a pick is the offer's position and the turn it was offered in", () => {
  assert.deepEqual(promptPickPayload(2, "turn-7"), { index: 2, turnId: "turn-7" });
  // An offer that named no turn sends none, rather than an empty one the
  // server would refuse.
  assert.deepEqual(promptPickPayload(0, null), { index: 0 });
});

test("the offers keep the turn your_prompt_choices named", () => {
  useGameStore.getState().setMyPromptChoices(["anchor", "balloon"], 15, "turn-7");
  const state = useGameStore.getState();
  assert.deepEqual(state.promptChoices, ["anchor", "balloon"]);
  assert.equal(state.promptChoicesTurnId, "turn-7");
  // The next offer replaces both together, so an old turn never goes out with
  // new choices.
  useGameStore.getState().setMyPromptChoices(["castle"], 15, "turn-8");
  assert.equal(useGameStore.getState().promptChoicesTurnId, "turn-8");
});
