import assert from "node:assert/strict";
import test from "node:test";

import {
  canCastRestartVote,
  restartVoteCounts,
  secondsUntil,
} from "../src/lib/restartVote.ts";

const vote = {
  status: "voting",
  proposerId: "one",
  proposerNickname: "One",
  eligibleVoterIds: ["one", "two", "three"],
  yesVoterIds: ["one", "outsider"],
  noVoterIds: ["two"],
  castVotes: [
    { playerId: "one", vote: true },
    { playerId: "two", vote: false },
    { playerId: "outsider", vote: true },
  ],
  requiredVotes: 2,
  expiresAt: 21_000,
  restartAt: null,
};

test("restart vote counts use the snapshotted eligible population", () => {
  assert.deepEqual(restartVoteCounts(vote), {
    yes: 1,
    no: 1,
    pending: 1,
    total: 3,
  });
});

test("only connected non-AFK snapshot participants may vote", () => {
  const player = {
    playerId: "three",
    nickname: "Three",
    score: 0,
    connected: true,
    isHost: false,
    isSpectator: false,
    isAfk: false,
  };
  assert.equal(canCastRestartVote(vote, player), true);
  assert.equal(canCastRestartVote(vote, { ...player, isAfk: true }), false);
  assert.equal(canCastRestartVote(vote, { ...player, connected: false }), false);
  assert.equal(canCastRestartVote(vote, { ...player, playerId: "late" }), false);
  assert.equal(canCastRestartVote({ ...vote, status: "approved" }, player), false);
});

test("restart countdown rounds up and never becomes negative", () => {
  assert.equal(secondsUntil(21_000, 19_001), 2);
  assert.equal(secondsUntil(21_000, 21_000), 0);
  assert.equal(secondsUntil(21_000, 22_000), 0);
  assert.equal(secondsUntil(null, 0), 0);
});
