import assert from "node:assert/strict";
import test from "node:test";

import { useGameStore } from "../src/store/gameStore.ts";

// The recap left `room_state` in #871: it arrives as `game_ended` or
// `last_game`, and the store has to keep it, drop it and act on it itself.

function roomState(id, state) {
  return {
    id, code: id.toUpperCase(), name: id, isPublic: false, maxPlayers: 8, rounds: 3,
    customPromptCount: 0, customPromptsOnly: false, drawingSeconds: 80, hintMode: "checkpoints",
    scoringMode: "default", spectatorsSeePrompt: false, hideMaskedPrompt: false, state,
    moderation: { eligibleVoterIds: [], requiredVotes: 1 }, restartVote: null,
    restartVoteCooldownUntil: 0, players: [],
  };
}

const recap = {
  scores: [{ playerId: "p1", nickname: "Ann", score: 300 }],
  highlights: [{ kind: "most_reacted_drawing", prompt: "cat", reactionCount: 1, drawingIndex: 0, turnId: "t1" }],
  drawings: [{ index: 0, turnId: "t1", reactions: [{ playerId: "p2", emoji: "wow" }], roundNumber: 1, turnNumber: 1 }],
};

test("a different room's waiting state does not inherit the last room's recap", () => {
  const store = useGameStore.getState();
  store.reset();
  store.setRoomState(roomState("first", "waiting"));
  store.applyLastGame(recap);
  store.setRoomState(roomState("first", "waiting"));
  assert.deepEqual(useGameStore.getState().finalScores, recap.scores, "the same room keeps it");

  store.setRoomState(roomState("second", "waiting"));
  const after = useGameStore.getState();
  assert.equal(after.finalScores, null);
  assert.deepEqual(after.drawingRecap, []);
  assert.deepEqual(after.gameHighlights, []);
  assert.deepEqual(after.drawingReactions, {});
});

test("a room switched to from a game-over screen opens waiting, not on that screen", () => {
  const store = useGameStore.getState();
  store.reset();
  store.setRoomState(roomState("first", "waiting"));
  store.endGame(recap);
  assert.equal(useGameStore.getState().phase, "game_end");

  store.setRoomState(roomState("second", "waiting"));
  store.applyLastGame(recap);
  const after = useGameStore.getState();
  assert.equal(after.phase, "idle", "the second room's recap, without its end-of-game moment");
  assert.deepEqual(after.finalScores, recap.scores);

  // The same room's own updates keep a game-over screen that is up.
  store.endGame(recap);
  store.setRoomState(roomState("second", "waiting"));
  assert.equal(useGameStore.getState().phase, "game_end");
});

test("last_game moves a tab that missed the game's end into the waiting room", () => {
  const store = useGameStore.getState();
  store.reset();
  store.setRoomState(roomState("room", "playing"));
  useGameStore.setState({ phase: "drawing" });

  store.applyLastGame(recap);
  const after = useGameStore.getState();
  assert.equal(after.roomState, "waiting");
  assert.equal(after.phase, "idle", "the recap, not the end-of-game moment replayed");
  assert.deepEqual(after.finalScores, recap.scores);

  useGameStore.setState({ phase: "game_end" });
  store.applyLastGame(recap);
  assert.equal(useGameStore.getState().phase, "game_end", "a game-over screen already up stays up");
});
