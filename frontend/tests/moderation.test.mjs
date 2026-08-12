import assert from "node:assert/strict";
import test from "node:test";

import {
  canCastModerationVote,
  eligibleModerationVotes,
} from "../src/lib/moderation.ts";

const moderation = {
  eligibleVoterIds: ["player", "target", "afk-player"],
  requiredVotes: 2,
};

test("frontend uses the server-provided moderation population and threshold", () => {
  assert.equal(moderation.requiredVotes, 2);
  assert.equal(canCastModerationVote(moderation, "player"), true);
  assert.equal(canCastModerationVote(moderation, "afk-player"), true);
  assert.equal(canCastModerationVote(moderation, "spectator"), false);
});

test("displayed vote totals exclude votes outside the server population", () => {
  assert.deepEqual(
    eligibleModerationVotes(moderation, ["player", "afk-player", "spectator"]),
    ["player", "afk-player"],
  );
});
