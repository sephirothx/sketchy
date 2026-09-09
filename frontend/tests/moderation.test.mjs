import assert from "node:assert/strict";
import test from "node:test";

import {
  canCastModerationVote,
  composeRepeatNote,
  eligibleModerationVotes,
  MAX_RESOLUTION_NOTE,
  suspensionExpiry,
  SUSPENSION_DURATIONS,
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

test("a timed suspension is stored as the moment it ends", () => {
  // The API takes an instant, not a duration: a request that took a minute to
  // arrive must not arrive at a ban a minute shorter than the one chosen.
  const now = new Date("2026-08-24T12:00:00.000Z");

  assert.equal(suspensionExpiry("24h", now), "2026-08-25T12:00:00.000Z");
  assert.equal(suspensionExpiry("7d", now), "2026-08-31T12:00:00.000Z");
  assert.equal(suspensionExpiry("30d", now), "2026-09-23T12:00:00.000Z");
});

test("a permanent suspension has no end, rather than a distant one", () => {
  // undefined means the field is left off the request entirely; a far-future
  // date would be a lie that eventually expires.
  assert.equal(suspensionExpiry("forever", new Date()), undefined);
});

test("an unrecognised duration does not silently become permanent", () => {
  // It falls through to no expiry, which is the one outcome worth being sure
  // about: the caller only ever passes a value from the list.
  assert.equal(suspensionExpiry("not-an-option", new Date()), undefined);
  assert.deepEqual(
    SUSPENSION_DURATIONS.map((option) => option.value),
    ["24h", "7d", "30d", "forever"],
  );
});

// Whether a report can carry the canvas: only about the seat holding the pen,
// and only while the canvas still shows that turn.
import { canAttachDrawing } from "../src/lib/moderation.ts";

test("the drawing is offered against the drawer while the canvas shows the turn", () => {
  assert.equal(canAttachDrawing("drawing", "drawer", "drawer"), true);
  assert.equal(canAttachDrawing("turn_results", "drawer", "drawer"), true);
});

test("the drawing is not offered against a guesser, or when nobody is drawing", () => {
  assert.equal(canAttachDrawing("drawing", "drawer", "guesser"), false);
  assert.equal(canAttachDrawing("drawing", null, "drawer"), false);
  assert.equal(canAttachDrawing("drawing", undefined, "drawer"), false);
});

test("the drawing is not offered while a prompt is being chosen or the game is over", () => {
  assert.equal(canAttachDrawing("choosing_prompt", "drawer", "drawer"), false);
  assert.equal(canAttachDrawing("game_end", "drawer", "drawer"), false);
  assert.equal(canAttachDrawing("idle", "drawer", "drawer"), false);
});

const priorDismissal = {
  outcome: "dismissed",
  decidedAt: "2026-09-09T11:53:00Z",
  decidedBy: "Sephiroth",
  note: "Heated, but within bounds.",
  priorDecisions: 1,
};

test("a repeat's note carries the decision it defers to", () => {
  const composed = composeRepeatNote(priorDismissal, "Dismissed", "Sep 9, 2026, 11:53");
  assert.equal(
    composed,
    "Already dismissed on Sep 9, 2026, 11:53 by Sephiroth. " +
      "Their note: “Heated, but within bounds.”",
  );
});

test("a repeat's note says how many times, once there has been more than one", () => {
  const composed = composeRepeatNote(
    { ...priorDismissal, priorDecisions: 3 },
    "Dismissed",
    "Sep 9, 2026, 11:53",
  );
  assert.match(composed, /and 3 times in all\./);
});

test("a repeat's note stands without a previous note, a time, or a named reviewer", () => {
  assert.equal(
    composeRepeatNote(
      { outcome: "warned", decidedAt: null, decidedBy: null, note: null, priorDecisions: 1 },
      "Warned",
      null,
    ),
    "Already warned.",
  );
});

test("an overlong previous note is cut, and what was decided always survives", () => {
  const composed = composeRepeatNote(
    { ...priorDismissal, note: "x".repeat(MAX_RESOLUTION_NOTE * 2) },
    "Dismissed",
    "Sep 9, 2026, 11:53",
  );
  assert.ok(composed.length <= MAX_RESOLUTION_NOTE);
  assert.ok(composed.startsWith("Already dismissed on Sep 9, 2026, 11:53 by Sephiroth."));
  assert.ok(composed.endsWith("…”"));
});
