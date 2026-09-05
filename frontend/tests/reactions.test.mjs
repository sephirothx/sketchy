import assert from "node:assert/strict";
import test from "node:test";

import {
  applyReactionEvent,
  compactTally,
  glyphFor,
  myReaction,
  offeredReactions,
  reactionEligibility,
  reactionFor,
  REACTION_GLYPHS,
  REACTION_SET_VERSION,
  RETIRED_REACTION_CODES,
  tallyReactions,
  totalReactions,
} from "../src/lib/reactions.ts";

test("the set is frozen: four codes, version 1, in picker order", () => {
  assert.equal(REACTION_SET_VERSION, 1);
  assert.deepEqual(
    REACTION_GLYPHS.map((emoji) => emoji.code),
    ["heart", "laugh", "wow", "fire"],
  );
  for (const emoji of REACTION_GLYPHS) {
    assert.ok(emoji.glyph.length > 0 && emoji.label.length > 0, emoji.code);
  }
});

test("a retired code still renders from history but is no longer offered", () => {
  // The rule the stored-drawing decoders follow, applied to a code: retiring
  // one changes what a player can pick, never what an old row means.
  const retired = new Set([...RETIRED_REACTION_CODES, "wow"]);
  const offered = REACTION_GLYPHS.filter((emoji) => !retired.has(emoji.code));
  assert.deepEqual(
    offered.map((emoji) => emoji.code),
    ["heart", "laugh", "fire"],
  );
  assert.equal(glyphFor("wow"), "\u{1F62E}", "the glyph table keeps a retired code");
  assert.equal(reactionFor("wow").label, "Wow");
  // Today nothing is retired, so the picker offers the whole set.
  assert.deepEqual(offeredReactions(), REACTION_GLYPHS);
});

test("a code this build has never heard of still gets a face", () => {
  const unknown = reactionFor("sparkle");
  assert.equal(unknown.code, "sparkle");
  assert.ok(unknown.glyph.length > 0);
  assert.equal(unknown.label, "Reaction");
});

test("a tally counts per code and compacts in picker order with strangers last", () => {
  const reactions = [
    { playerId: "a", emoji: "fire" },
    { playerId: "b", emoji: "heart" },
    { playerId: "c", emoji: "fire" },
    { playerId: "d", emoji: "sparkle" },
  ];
  const tally = tallyReactions(reactions);
  assert.deepEqual(tally, { fire: 2, heart: 1, sparkle: 1 });
  assert.equal(totalReactions(tally), 4);
  assert.deepEqual(
    compactTally({ ...tally, laugh: 0 }).map((chip) => [chip.code, chip.count]),
    [["heart", 1], ["fire", 2], ["sparkle", 1]],
  );
  assert.deepEqual(compactTally({}), []);
});

test("a broadcast replaces, adds or removes one seat's reaction", () => {
  const start = [{ playerId: "a", emoji: "heart" }];
  const added = applyReactionEvent(start, { playerId: "b", emoji: "laugh" });
  assert.deepEqual(added, [
    { playerId: "a", emoji: "heart" },
    { playerId: "b", emoji: "laugh" },
  ]);
  const changed = applyReactionEvent(added, { playerId: "a", emoji: "fire" });
  assert.deepEqual(tallyReactions(changed), { laugh: 1, fire: 1 }, "a change is not a second reaction");
  const removed = applyReactionEvent(changed, { playerId: "a", emoji: null });
  assert.deepEqual(removed, [{ playerId: "b", emoji: "laugh" }]);
  assert.equal(myReaction(changed, "a"), "fire");
  assert.equal(myReaction(removed, "a"), null);
  assert.equal(myReaction(removed, null), null);
});

test("the picker is offered only where pressing it can work", () => {
  assert.equal(reactionEligibility({ isRegistered: true }), "ok");
  assert.equal(reactionEligibility({ isRegistered: false }), "guest");
  assert.equal(reactionEligibility({ isRegistered: true, isSpectator: true }), "spectator");
  assert.equal(reactionEligibility({ isRegistered: true, isDrawer: true }), "drawer");
  // A spectator who is also a guest is told they are a spectator: no account
  // would change that.
  assert.equal(reactionEligibility({ isRegistered: false, isSpectator: true }), "spectator");
  assert.equal(reactionEligibility({ isRegistered: true, open: false }), "closed");
});
