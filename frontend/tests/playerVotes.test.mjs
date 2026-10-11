import assert from "node:assert/strict";
import test from "node:test";

import { openPlayerVotes, votesAwaitingMe } from "../src/lib/playerVotes.ts";

const moderation = { eligibleVoterIds: ["ana", "bo", "cy", "di"], requiredVotes: 3 };
const seat = (playerId, extra = {}) => ({
  playerId, nickname: playerId.toUpperCase(), score: 0, connected: true,
  isHost: false, isSpectator: false, isAfk: false, ...extra,
});

test("a kick and an AFK vote are read off the tallies every seat already has (#1422)", () => {
  const players = [seat("ana"), seat("bo", { kickVotes: ["ana"], afkVotes: ["cy", "ana"] }), seat("cy")];
  const votes = openPlayerVotes(players, moderation, "cy");
  assert.deepEqual(
    votes.map(({ key, count, required, mine, canVote, aboutMe }) => ({ key, count, required, mine, canVote, aboutMe })),
    [
      { key: "kick:bo", count: 1, required: 3, mine: false, canVote: true, aboutMe: false },
      { key: "afk:bo", count: 2, required: 3, mine: true, canVote: true, aboutMe: false },
    ],
  );
  assert.equal(votes[0].targetNickname, "BO");
  assert.deepEqual(votesAwaitingMe(votes).map((vote) => vote.key), ["kick:bo"]);
});

test("the target sees its vote but cannot cast in it, and a spectator cannot cast at all", () => {
  const players = [seat("bo", { kickVotes: ["ana"] })];
  const [aboutMe] = openPlayerVotes(players, moderation, "bo");
  assert.equal(aboutMe.aboutMe, true);
  assert.equal(aboutMe.canVote, false);
  const [watched] = openPlayerVotes(players, moderation, "spectator");
  assert.equal(watched.canVote, false);
  assert.deepEqual(votesAwaitingMe([aboutMe, watched]), []);
});

test("ballots from seats that may no longer vote do not count, and an AFK vote on an AFK seat is over", () => {
  const players = [
    seat("bo", { kickVotes: ["gone"] }),
    seat("cy", { isAfk: true, afkVotes: ["ana"] }),
    seat("di", { kickVotes: ["gone", "ana"] }),
  ];
  const votes = openPlayerVotes(players, moderation, "ana");
  assert.deepEqual(votes.map((vote) => [vote.key, vote.count, vote.mine]), [["kick:di", 1, true]]);
});
